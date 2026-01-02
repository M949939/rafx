import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class TypeInfo:
    name: str
    is_pointer: bool = False
    is_const: bool = False
    array_size: Optional[int] = None
    array_size_2d: Optional[int] = None


@dataclass
class EnumValue:
    name: str
    value: int


@dataclass
class Enum:
    name: str
    underlying_type: str
    values: List[EnumValue] = field(default_factory=list)
    is_anonymous: bool = False


@dataclass
class Field:
    name: str
    type_info: TypeInfo


@dataclass
class Struct:
    name: str
    fields: List[Field] = field(default_factory=list)
    is_union: bool = False
    is_opaque: bool = False


@dataclass
class Function:
    name: str
    ret_type: TypeInfo
    params: List[Field] = field(default_factory=list)


@dataclass
class Typedef:
    name: str
    target_type: TypeInfo


class ApiModule:
    def __init__(self):
        self.enums: List[Enum] = []
        self.structs_map: Dict[str, Struct] = {}
        self.functions: List[Function] = []
        self.typedefs: List[Typedef] = []

    def add_struct(self, s: Struct):
        if s.name in self.structs_map:
            existing = self.structs_map[s.name]
            if existing.is_opaque and not s.is_opaque:
                self.structs_map[s.name] = s
        else:
            self.structs_map[s.name] = s


#
# ast parser
#


class ClangAstParser:
    def __init__(self, header_file):
        self.header_file = header_file
        self.header_filename = os.path.basename(header_file).replace("\\", "/").lower()
        self.module = ApiModule()
        self.processed_ids = set()
        self.node_index = {}

        self.type_map = {
            "unsigned int": "u32",
            "uint32_t": "u32",
            "int": "i32",
            "int32_t": "i32",
            "unsigned char": "u8",
            "uint8_t": "u8",
            "signed char": "i8",
            "int8_t": "i8",
            "char": "c_char",
            "unsigned short": "u16",
            "uint16_t": "u16",
            "short": "i16",
            "int16_t": "i16",
            "unsigned long long": "u64",
            "uint64_t": "u64",
            "long long": "i64",
            "int64_t": "i64",
            "float": "f32",
            "double": "f64",
            "void": "c_void",
            "_Bool": "bool",
            "bool": "bool",
            "size_t": "usize",
            "intptr_t": "isize",
            "uintptr_t": "usize",
            "ptrdiff_t": "isize",
        }

        self.ignore_names = {
            "va_list",
            "__builtin_va_list",
            "__va_list_tag",
            "wchar_t",
            "max_align_t",
            "__int128_t",
            "__uint128_t",
            "int_least8_t",
            "int_least16_t",
            "int_least32_t",
            "int_least64_t",
            "uint_least8_t",
            "uint_least16_t",
            "uint_least32_t",
            "uint_least64_t",
            "int_fast8_t",
            "int_fast16_t",
            "int_fast32_t",
            "int_fast64_t",
            "uint_fast8_t",
            "uint_fast16_t",
            "uint_fast32_t",
            "uint_fast64_t",
            "intmax_t",
            "uintmax_t",
            "__vcrt_bool",
            "__security_cookie",
            "_StackCookie",
            "__va_start",
            "__security_init_cookie",
            "__security_check_cookie",
            "__report_gsfailure",
        }

    def run_clang(self) -> dict:
        cmd = [
            "clang",
            "-Xclang",
            "-ast-dump=json",
            "-fsyntax-only",
            "-Wno-everything",
            self.header_file,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True, encoding="utf-8"
            )
            sys.setrecursionlimit(10000)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            sys.stderr.write(f"Clang Error:\n{e.stderr}\n")
            sys.exit(1)

    def index_nodes(self, root):
        if isinstance(root, dict):
            if "id" in root:
                if root["id"] not in self.node_index or "inner" in root:
                    self.node_index[root["id"]] = root
            for value in root.values():
                self.index_nodes(value)
        elif isinstance(root, list):
            for item in root:
                self.index_nodes(item)

    def is_valid_loc(self, node):
        loc = node.get("loc")
        if not loc:
            return False
        if "file" not in loc:
            return True
        node_file = loc["file"].replace("\\", "/").lower()
        return node_file.endswith(self.header_filename)

    def evaluate_expr(self, node) -> int:
        kind = node.get("kind")
        if kind == "IntegerLiteral":
            return int(node.get("value", 0))

        if "inner" in node and len(node["inner"]) > 0:
            if kind == "BinaryOperator" and len(node["inner"]) >= 2:
                op = node.get("opcode")
                l = self.evaluate_expr(node["inner"][0])
                r = self.evaluate_expr(node["inner"][1])
                try:
                    if op == "<<":
                        return l << r
                    if op == ">>":
                        return l >> r
                    if op == "|":
                        return l | r
                    if op == "&":
                        return l & r
                    if op == "+":
                        return l + r
                    if op == "-":
                        return l - r
                    if op == "*":
                        return l * r
                    if op == "/":
                        return int(l / r)
                except:
                    pass
            return self.evaluate_expr(node["inner"][0])
        return 0

    def parse_type(self, qual_type: str) -> TypeInfo:
        t = qual_type
        dims = re.findall(r"\[(\d+)\]", t)
        array_size = None
        array_size_2d = None

        if len(dims) > 0:
            if len(dims) == 1:
                array_size = int(dims[0])
            elif len(dims) == 2:
                array_size_2d = int(dims[0])
                array_size = int(dims[1])
            t = re.sub(r"\[\d+\]", "", t).strip()

        is_const = "const " in t
        t = t.replace("const ", "").strip()
        is_pointer = "*" in t
        t = t.replace("*", "").strip()
        t = t.replace("struct ", "").replace("union ", "").replace("enum ", "").strip()

        if t in self.type_map:
            t = self.type_map[t]

        return TypeInfo(
            name=t,
            is_pointer=is_pointer,
            is_const=is_const,
            array_size=array_size,
            array_size_2d=array_size_2d,
        )

    def parse_fields(self, record_node, parent_name="") -> List[Field]:
        fields = []
        inner_nodes = record_node.get("inner", [])

        for child in inner_nodes:
            kind = child["kind"]
            if kind == "RecordDecl" and not child.get("name"):
                nested_name = f"{parent_name}_Data" if parent_name else "AnonymousInner"
                self.visit_record(child, forced_name=nested_name)
                fields.append(Field("data", TypeInfo(nested_name)))
            elif kind == "FieldDecl":
                fname = child.get("name")
                if not fname:
                    continue
                ftype = self.parse_type(child["type"]["qualType"])
                fields.append(Field(fname, ftype))
        return fields

    def visit_record(self, node, forced_name=None):
        node_id = node.get("id")
        if node_id in self.processed_ids:
            return
        name = forced_name if forced_name else node.get("name", "")
        if not name:
            return

        self.processed_ids.add(node_id)
        kind = node.get("tagUsed", "struct")
        is_union = kind == "union"

        has_fields = False
        if "inner" in node:
            for c in node["inner"]:
                if c["kind"] in ("FieldDecl", "RecordDecl"):
                    has_fields = True
                    break

        is_complete = node.get("completeDefinition", False) or has_fields

        if not is_complete:
            self.module.add_struct(Struct(name, [], is_union, is_opaque=True))
        else:
            fields = self.parse_fields(node, parent_name=name)
            self.module.add_struct(Struct(name, fields, is_union, is_opaque=False))

    def visit_typedef(self, node):
        name = node.get("name")
        if not name or name in self.ignore_names:
            return

        # Helper to drill down into the typedef
        def resolve_underlying(n):
            if "ownedTagDecl" in n:
                candidate = n["ownedTagDecl"]
                if (
                    "id" in candidate
                    and "inner" not in candidate
                    and candidate["id"] in self.node_index
                ):
                    candidate = self.node_index[candidate["id"]]
                return candidate
            if "inner" in n:
                for c in n["inner"]:
                    if c["kind"] == "ElaboratedType":
                        res = resolve_underlying(c)
                        if res:
                            return res
                    if c["kind"] in ("RecordDecl", "EnumDecl"):
                        if (
                            "id" in c
                            and "inner" not in c
                            and c["id"] in self.node_index
                        ):
                            return self.node_index[c["id"]]
                        return c
            return None

        underlying = resolve_underlying(node)

        if underlying:
            if underlying["kind"] == "RecordDecl":
                # typedef struct { } Name;
                self.visit_record(underlying, forced_name=name)
                return
            elif underlying["kind"] == "EnumDecl":
                # typedef enum { } Name;
                self.module.typedefs.append(Typedef(name, TypeInfo("u32")))
                return

        # Normal typedef
        qual_type = node["type"]["qualType"]
        target = self.parse_type(qual_type)

        if name in self.type_map:
            return
        if target.name == name and not target.is_pointer:
            return

        self.module.typedefs.append(Typedef(name, target))

    def visit_enum(self, node):
        name = node.get("name", "")
        is_anon = not name
        fixed_underlying = node.get("fixedUnderlyingType", {}).get("qualType", "u32")
        if fixed_underlying in self.type_map:
            fixed_underlying = self.type_map[fixed_underlying]

        values = []
        next_val = 0
        for child in node.get("inner", []):
            if child["kind"] == "EnumConstantDecl":
                val_name = child["name"]
                val = next_val
                if "inner" in child:
                    val = self.evaluate_expr(child)
                values.append(EnumValue(val_name, val))
                next_val = val + 1

        self.module.enums.append(Enum(name, fixed_underlying, values, is_anon))

    def visit_function(self, node):
        name = node.get("name")
        if not name or name in self.ignore_names or "operator" in name:
            return

        raw_type = node["type"]["qualType"]
        ret_str = raw_type.split("(")[0].strip()
        ret_type = self.parse_type(ret_str)

        params = []
        for child in node.get("inner", []):
            if child["kind"] == "ParmVarDecl":
                pname = child.get("name", "arg")
                ptype = self.parse_type(child["type"]["qualType"])
                params.append(Field(pname, ptype))

        self.module.functions.append(Function(name, ret_type, params))

    def parse(self):
        data = self.run_clang()
        root = data["inner"]
        self.index_nodes(data)

        for node in root:
            if not self.is_valid_loc(node):
                continue
            kind = node["kind"]
            if kind == "RecordDecl":
                self.visit_record(node)
            elif kind == "TypedefDecl":
                self.visit_typedef(node)
            elif kind == "EnumDecl":
                self.visit_enum(node)
            elif kind == "FunctionDecl":
                self.visit_function(node)

        return self.module
