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
    comment: Optional[str] = None


@dataclass
class Enum:
    name: str
    underlying_type: str
    values: List[EnumValue] = field(default_factory=list)
    is_anonymous: bool = False
    is_bitflags: bool = False
    comment: Optional[str] = None
    ast_id: Optional[int] = None


@dataclass
class Field:
    name: str
    type_info: TypeInfo
    comment: Optional[str] = None


@dataclass
class Struct:
    name: str
    fields: List[Field] = field(default_factory=list)
    is_union: bool = False
    is_opaque: bool = False
    comment: Optional[str] = None


@dataclass
class Function:
    name: str
    ret_type: TypeInfo
    params: List[Field] = field(default_factory=list)
    comment: Optional[str] = None


@dataclass
class Typedef:
    name: str
    target_type: TypeInfo
    comment: Optional[str] = None


class ApiModule:
    def __init__(self):
        self.enums: List[Enum] = []
        self.enum_map: Dict[int, Enum] = {}
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

    def add_enum(self, e: Enum):
        self.enums.append(e)
        if e.ast_id:
            self.enum_map[e.ast_id] = e


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
            "-fparse-all-comments",
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
        return loc["file"].replace("\\", "/").lower().endswith(self.header_filename)

    def extract_comment_text(self, node) -> str:
        text = ""
        if node["kind"] == "TextComment":
            text += node.get("text", "")
        elif "inner" in node:
            for child in node["inner"]:
                text += self.extract_comment_text(child)
        return text

    def clean_comment(self, raw_comment: Optional[str]) -> Optional[str]:
        if not raw_comment:
            return None
        lines = raw_comment.splitlines()
        cleaned = []
        for line in lines:
            line = line.strip()
            if line.startswith("*"):
                line = line[1:].strip()
            cleaned.append(line)
        return "\n".join(cleaned).strip()

    def evaluate_expr(self, node) -> int:
        kind = node.get("kind")
        if kind == "IntegerLiteral":
            return int(node.get("value", 0))

        inner = [
            n
            for n in node.get("inner", [])
            if n.get("kind") != "FullComment" and n.get("kind") != "TextComment"
        ]

        if len(inner) > 0:
            if kind == "BinaryOperator" and len(inner) >= 2:
                op = node.get("opcode")
                l = self.evaluate_expr(inner[0])
                r = self.evaluate_expr(inner[1])
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
            return self.evaluate_expr(inner[0])
        return 0

    def parse_type(self, qual_type: str) -> TypeInfo:
        t = qual_type
        dims = re.findall(r"\[(\d+)\]", t)
        array_size, array_size_2d = None, None
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
        inner = record_node.get("inner", [])
        comment = None
        for child in inner:
            kind = child["kind"]
            if kind == "FullComment":
                comment = self.clean_comment(self.extract_comment_text(child))
                continue
            if kind == "RecordDecl" and not child.get("name"):
                nested = f"{parent_name}_Data" if parent_name else "AnonymousInner"
                self.visit_record(child, forced_name=nested, comment=comment)
                fields.append(Field("data", TypeInfo(nested), comment=comment))
                comment = None
            elif kind == "FieldDecl":
                fname = child.get("name")
                if fname:
                    fields.append(
                        Field(
                            fname,
                            self.parse_type(child["type"]["qualType"]),
                            comment=comment,
                        )
                    )
                comment = None
        return fields

    def visit_record(self, node, forced_name=None, comment=None):
        if node.get("id") in self.processed_ids:
            return
        name = forced_name if forced_name else node.get("name", "")
        if not name:
            return
        self.processed_ids.add(node.get("id"))
        is_union = node.get("tagUsed") == "union"
        has_fields = any(
            c["kind"] in ("FieldDecl", "RecordDecl") for c in node.get("inner", [])
        )
        is_complete = node.get("completeDefinition", False) or has_fields
        if not is_complete:
            self.module.add_struct(
                Struct(name, [], is_union, is_opaque=True, comment=comment)
            )
        else:
            self.module.add_struct(
                Struct(
                    name,
                    self.parse_fields(node, parent_name=name),
                    is_union,
                    is_opaque=False,
                    comment=comment,
                )
            )

    def resolve_underlying_decl(self, node):
        if "ownedTagDecl" in node:
            decl = node["ownedTagDecl"]
            if "id" in decl and "inner" not in decl and decl["id"] in self.node_index:
                return self.node_index[decl["id"]]
            return decl

        # search in inner for ElaboratedType with ownedTagDecl
        if "inner" in node:
            for child in node["inner"]:
                if child["kind"] in ("RecordDecl", "EnumDecl"):
                    return child
                if child["kind"] == "ElaboratedType" and "ownedTagDecl" in child:
                    decl = child["ownedTagDecl"]
                    if (
                        "id" in decl
                        and "inner" not in decl
                        and decl["id"] in self.node_index
                    ):
                        return self.node_index[decl["id"]]
                    return decl
        return None

    def visit_typedef(self, node, comment=None, last_typedef_tracker=None):
        name = node.get("name")
        if not name or name in self.ignore_names:
            return

        underlying = self.resolve_underlying_decl(node)

        if underlying:
            if underlying["kind"] == "RecordDecl":
                self.visit_record(underlying, forced_name=name, comment=comment)
                if last_typedef_tracker is not None:
                    last_typedef_tracker[0] = None
                return
            elif underlying["kind"] == "EnumDecl":
                self.visit_enum(underlying, inferred_name=name, comment=comment)
                if last_typedef_tracker is not None:
                    last_typedef_tracker[0] = None
                return

        target = self.parse_type(node["type"]["qualType"])

        if name not in self.type_map and (target.name != name or target.is_pointer):
            self.module.typedefs.append(Typedef(name, target, comment=comment))

        # ugly hack to track RFX_ENUM
        if last_typedef_tracker is not None:
            if not target.is_pointer and target.name in [
                "u8",
                "u16",
                "u32",
                "u64",
                "i8",
                "i16",
                "i32",
                "i64",
            ]:
                last_typedef_tracker[0] = name
            else:
                last_typedef_tracker[0] = None

    def visit_enum(self, node, comment=None, inferred_name=None, inferred_type=None):
        name = node.get("name", "")
        if not name and inferred_name:
            name = inferred_name

        fixed = node.get("fixedUnderlyingType", {}).get("qualType", "u32")
        if "fixedUnderlyingType" not in node and inferred_type:
            fixed = inferred_type
        if fixed in self.type_map:
            fixed = self.type_map[fixed]

        values = []
        next_val = 0
        val_comment = None

        for child in node.get("inner", []):
            if child["kind"] == "FullComment":
                val_comment = self.clean_comment(self.extract_comment_text(child))
                continue
            if child["kind"] == "EnumConstantDecl":
                val = next_val
                expr_nodes = [
                    n for n in child.get("inner", []) if n.get("kind") != "FullComment"
                ]
                if expr_nodes:
                    val = self.evaluate_expr(child)

                values.append(EnumValue(child["name"], val, comment=val_comment))
                next_val = val + 1
                val_comment = None

        is_bitflags = False
        if name and ("Flags" in name or "Bits" in name):
            is_bitflags = True

        self.module.add_enum(
            Enum(name, fixed, values, not name, is_bitflags, comment, node.get("id"))
        )

    def visit_function(self, node, comment=None):
        name = node.get("name")
        if not name or name in self.ignore_names or "operator" in name:
            return
        ret = self.parse_type(node["type"]["qualType"].split("(")[0].strip())
        params = []
        for c in node.get("inner", []):
            if c["kind"] == "ParmVarDecl":
                params.append(
                    Field(c.get("name", "arg"), self.parse_type(c["type"]["qualType"]))
                )
        self.module.functions.append(Function(name, ret, params, comment=comment))

    def parse(self):
        data = self.run_clang()
        root = data["inner"]
        self.index_nodes(data)

        comment = None
        last_typedef = [None]

        for node in root:
            if not self.is_valid_loc(node):
                comment, last_typedef[0] = None, None
                continue

            kind = node["kind"]
            if kind == "FullComment":
                comment = self.clean_comment(self.extract_comment_text(node))
                continue

            if kind == "RecordDecl":
                self.visit_record(node, comment=comment)
                last_typedef[0] = None
            elif kind == "TypedefDecl":
                self.visit_typedef(
                    node, comment=comment, last_typedef_tracker=last_typedef
                )
            elif kind == "EnumDecl":
                self.visit_enum(node, comment=comment, inferred_name=last_typedef[0])
                last_typedef[0] = None
            elif kind == "FunctionDecl":
                self.visit_function(node, comment=comment)
                last_typedef[0] = None

            if kind not in ["DLLImportAttr", "DLLExportAttr", "VisibilityAttr"]:
                comment = None
        return self.module
