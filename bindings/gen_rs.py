import re
from typing import Dict, List, Optional, Set

from gen_ast import *


class RustGenerator:
    def __init__(self, module: ApiModule):
        self.module = module
        self.output = []
        self.name_map: Dict[str, str] = {}
        self.handle_types: Set[str] = set()
        self.union_types: Set[str] = set()

        self.primitives = {
            "u8": "u8",
            "u16": "u16",
            "u32": "u32",
            "u64": "u64",
            "i8": "i8",
            "i16": "i16",
            "i32": "i32",
            "i64": "i64",
            "f32": "f32",
            "f64": "f64",
            "bool": "bool",
            "usize": "usize",
            "isize": "isize",
            "c_char": "c_char",
            "c_void": "c_void",
        }

        self.preprocess()

    def strip_rfx(self, name: str) -> str:
        return re.sub(r"^(rfx|RFX|Rfx)_?", "", name)

    def preprocess(self):
        # identify handles and unions
        for s_name, s in self.module.structs_map.items():
            if s.is_opaque:
                self.handle_types.add(s_name)
            if s.is_union:
                self.union_types.add(s_name)

        for td in self.module.typedefs:
            if td.target_type.is_pointer and td.target_type.name not in self.primitives:
                self.handle_types.add(td.name)

        used_safe_names: Dict[str, str] = {}

        for h_name in sorted(self.handle_types):
            safe = self.strip_rfx(h_name)
            self.name_map[h_name] = safe
            used_safe_names[safe] = "handle"

        for s_name in sorted(self.module.structs_map.keys()):
            if s_name in self.name_map:
                continue
            safe = self.strip_rfx(s_name)
            if safe in used_safe_names:
                safe += "Struct"
            self.name_map[s_name] = safe
            used_safe_names[safe] = "struct"

        for enum in self.module.enums:
            if enum.is_anonymous or not enum.name:
                continue
            if enum.name in self.name_map:
                continue
            safe = self.strip_rfx(enum.name)
            if safe in used_safe_names:
                suffix = "Flags" if "Flags" in enum.name else "Enum"
                if not safe.endswith(suffix):
                    safe += suffix
            self.name_map[enum.name] = safe
            used_safe_names[safe] = "enum"

        for td in self.module.typedefs:
            if td.name in self.name_map:
                continue
            safe = self.strip_rfx(td.name)
            if safe in used_safe_names:
                safe += "Type"
            self.name_map[td.name] = safe
            used_safe_names[safe] = "typedef"

    def is_debug_safe(self, struct: Struct) -> bool:
        if struct.is_union:
            return False
        for f in struct.fields:
            if f.type_info.name in self.union_types:
                return False
            if "Data" in f.type_info.name or "union" in f.type_info.name:
                return False
        return True

    def to_snake_case(self, name: str) -> str:
        name = self.strip_rfx(name)
        s1 = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub("([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    def to_pascal_case(self, name: str) -> str:
        name = self.strip_rfx(name)
        return "".join(word.title() for word in name.split("_"))

    def to_rust_type(self, t: TypeInfo, is_sys: bool) -> str:
        base = t.name
        if base in ["unsigned int", "uint32_t"]:
            base = "u32"
        elif base in ["int", "int32_t"]:
            base = "i32"
        elif base in ["unsigned char", "uint8_t"]:
            base = "u8"
        elif base in ["_Bool"]:
            base = "bool"

        if not is_sys:
            if base in self.name_map:
                base = self.name_map[base]
            elif base not in self.primitives:
                base = f"sys::{base}"

        if t.array_size is not None:
            inner = self.to_rust_type(TypeInfo(t.name), is_sys)
            if t.array_size_2d is not None:
                return f"[[{inner}; {t.array_size}]; {t.array_size_2d}]"
            return f"[{inner}; {t.array_size}]"

        if t.is_pointer:
            ptr = "*const" if t.is_const else "*mut"
            if "void" in base:
                base = "c_void"
            if "char" in base:
                base = "c_char"
            return f"{ptr} {base}"

        return base

    def get_rust_repr(self, underlying: str) -> str:
        u = underlying.lower()
        if "unsigned" in u or "u8" in u or "u16" in u or "u32" in u or "u64" in u:
            if "char" in u or "8" in u:
                return "u8"
            if "short" in u or "16" in u:
                return "u16"
            if "long long" in u or "64" in u:
                return "u64"
            return "u32"
        else:
            if "char" in u or "8" in u:
                return "i8"
            if "short" in u or "16" in u:
                return "i16"
            if "long long" in u or "64" in u:
                return "i64"
            return "i32"

    def emit(self, line="", indent=0):
        self.output.append("    " * indent + line)

    def generate_sys_module(self):
        self.emit("pub mod sys {", 0)
        self.emit("use std::ffi::c_void; use std::os::raw::c_char;", 1)
        self.emit("", 1)

        for enum in self.module.enums:
            repr_type = self.get_rust_repr(enum.underlying_type)
            if not enum.is_anonymous:
                self.emit(f"pub type {enum.name} = {repr_type};", 1)
            for val in enum.values:
                self.emit(
                    f"pub const {val.name}: {enum.name if not enum.is_anonymous else repr_type} = {val.value};",
                    1,
                )

        for struct in self.module.structs_map.values():
            if struct.is_opaque:
                self.emit(
                    f"#[repr(C)] #[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)] pub struct {struct.name} {{ _unused: [u8; 0] }}",
                    1,
                )
            else:
                derive = (
                    "#[derive(Debug, Copy, Clone)]"
                    if self.is_debug_safe(struct)
                    else "#[derive(Copy, Clone)]"
                )
                self.emit(f"#[repr(C)] {derive}", 1)
                self.emit(
                    f"pub {'union' if struct.is_union else 'struct'} {struct.name} {{",
                    1,
                )
                for f in struct.fields:
                    fname = (
                        f"r#{f.name}"
                        if f.name in ["type", "box", "as", "mod"]
                        else f.name
                    )
                    self.emit(
                        f"pub {fname}: {self.to_rust_type(f.type_info, True)},", 2
                    )
                self.emit("}", 1)

        for td in self.module.typedefs:
            self.emit(
                f"pub type {td.name} = {self.to_rust_type(td.target_type, True)};", 1
            )

        self.emit("", 1)
        self.emit('unsafe extern "C" {', 1)
        for func in self.module.functions:
            ret = self.to_rust_type(func.ret_type, True)
            ret_str = (
                ""
                if ret in ["void", "c_void"] and not func.ret_type.is_pointer
                else f" -> {ret}"
            )
            params = [
                f"{p.name if p.name not in ['as', 'type'] else 'r#' + p.name}: {self.to_rust_type(p.type_info, True)}"
                for p in func.params
            ]
            self.emit(f"pub fn {func.name}({', '.join(params)}){ret_str};", 2)
        self.emit("}", 1)
        self.emit("}", 0)

    def generate_safe_typedefs(self):
        self.emit("//\n// Typedefs\n//")
        for raw, safe in self.name_map.items():
            is_def = (
                raw in self.handle_types
                or raw in self.module.structs_map
                or any(e.name == raw for e in self.module.enums)
            )
            if not is_def:
                self.emit(f"pub type {safe} = sys::{raw};")
        self.emit()

    def generate_safe_enums(self):
        self.emit("//\n// Enums\n//")
        for enum in self.module.enums:
            if enum.is_anonymous:
                continue
            name = self.name_map[enum.name]
            prefix = self.get_common_prefix(enum.values)
            repr_type = self.get_rust_repr(enum.underlying_type)

            if "Flags" in name:
                self.emit("bitflags::bitflags! {")
                self.emit(
                    "    #[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]",
                    1,
                )
                self.emit(f"    pub struct {name}: {repr_type} {{", 0)
                for val in enum.values:
                    vname = (
                        val.name[len(prefix) :]
                        if val.name.startswith(prefix)
                        else val.name
                    )
                    if not vname or vname[0].isdigit():
                        vname = "F" + vname
                    self.emit(f"const {vname} = sys::{val.name};", 2)
                self.emit("    }", 0)
                self.emit("}")
            else:
                self.emit(f"#[repr({repr_type})]")
                self.emit("#[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)]")
                self.emit(f"pub enum {name} {{")
                seen = set()
                for val in enum.values:
                    if val.value in seen:
                        continue
                    seen.add(val.value)
                    vname = (
                        val.name[len(prefix) :]
                        if val.name.startswith(prefix)
                        else val.name
                    )
                    vname = self.to_pascal_case(vname)
                    if vname in ["None", "Default"]:
                        vname += "_"
                    if not vname or vname[0].isdigit():
                        vname = "V" + vname
                    self.emit(f"{vname} = sys::{val.name} as {repr_type},", 1)
                self.emit("}")
            self.emit()

    def get_common_prefix(self, values: List[EnumValue]) -> str:
        if not values:
            return ""
        prefix = values[0].name
        for v in values[1:]:
            while not v.name.startswith(prefix) and prefix:
                prefix = prefix[:-1]
        if "_" in prefix:
            prefix = prefix[: prefix.rfind("_") + 1]
        return prefix

    def generate_safe_structs_and_handles(self):
        self.emit("//\n// Handles and structs\n//")
        for h_name in sorted(self.handle_types):
            name = self.name_map[h_name]
            self.emit(
                f"#[repr(transparent)] #[derive(Debug, Copy, Clone, PartialEq, Eq, Hash)] pub struct {name}(pub sys::{h_name});"
            )
            self.emit(
                f"impl {name} {{ pub fn as_raw(&self) -> sys::{h_name} {{ self.0 }} }}"
            )
            self.emit()

        for s_name, s in self.module.structs_map.items():
            if s.is_opaque or s_name in self.handle_types:
                continue
            name = self.name_map[s_name]
            derive = (
                "#[derive(Debug, Copy, Clone)]"
                if self.is_debug_safe(s)
                else "#[derive(Copy, Clone)]"
            )
            self.emit(f"#[repr(C)] {derive}")
            self.emit(f"pub struct {name} {{")
            for f in s.fields:
                fname = self.to_snake_case(f.name)
                if fname in ["type", "as", "box"]:
                    fname = f"r#{fname}"
                self.emit(f"pub {fname}: {self.to_rust_type(f.type_info, False)},", 1)
            self.emit("}")
            self.emit(
                f"impl Default for {name} {{ fn default() -> Self {{ unsafe {{ std::mem::zeroed() }} }} }}"
            )
            self.emit()

    def generate_functions(self):
        self.emit("//\n// Functions\n//")
        for handle_raw in sorted(self.handle_types):
            handle_safe = self.name_map[handle_raw]
            funcs = [
                f
                for f in self.module.functions
                if f.params
                and f.params[0].type_info.name == handle_raw
                and not f.params[0].type_info.is_pointer
            ]
            if funcs:
                self.emit(f"impl {handle_safe} {{")
                for f in funcs:
                    self.emit_func(f, is_method=True, handle_name=handle_raw)
                self.emit("}")

        for f in self.module.functions:
            is_method = (
                f.params
                and f.params[0].type_info.name in self.handle_types
                and not f.params[0].type_info.is_pointer
            )
            if not is_method:
                self.emit_func(f)

    def emit_func(self, func: Function, is_method=False, handle_name=""):
        name = self.to_snake_case(func.name)
        if is_method:
            handle_snake = self.to_snake_case(handle_name)
            name = name.replace(f"_{handle_snake}", "").replace(f"{handle_snake}_", "")
            if "command_list" in handle_snake and name.startswith("cmd_"):
                name = name[4:]

        params, call_args = [], []
        start = 1 if is_method else 0
        if is_method:
            params.append("&self")
            call_args.append("self.0")

        for i in range(start, len(func.params)):
            p = func.params[i]
            pname = self.to_snake_case(p.name)
            if pname in ["type", "as"]:
                pname = f"r#{pname}"

            t = p.type_info
            if t.is_pointer and t.name in ["char", "c_char"]:
                params.append(f"{pname}: &str")
                call_args.append(f"std::ffi::CString::new({pname}).unwrap().as_ptr()")
            elif t.is_pointer:
                safe_base = self.name_map.get(t.name, t.name)
                sys_base = f"sys::{t.name}" if t.name not in self.primitives else t.name
                params.append(f"{pname}: *mut {safe_base}")
                call_args.append(f"{pname} as *mut {sys_base}")
            elif t.name in self.name_map:
                safe_type = self.name_map[t.name]
                params.append(f"{pname}: {safe_type}")
                if t.name in self.handle_types:
                    call_args.append(f"{pname}.0")
                else:
                    is_enum = False
                    enum_underlying = "i32"
                    is_flags = False

                    for e in self.module.enums:
                        if self.name_map.get(e.name) == safe_type:
                            is_enum = True
                            enum_underlying = self.get_rust_repr(e.underlying_type)
                            is_flags = "Flags" in safe_type
                            break

                    if is_enum:
                        if is_flags:
                            call_args.append(f"{pname}.bits()")
                        else:
                            call_args.append(f"{pname} as {enum_underlying}")
                    else:
                        call_args.append(f"unsafe {{ std::mem::transmute({pname}) }}")
            else:
                params.append(f"{pname}: {self.to_rust_type(t, False)}")
                call_args.append(pname)

        ret_rust = self.to_rust_type(func.ret_type, False)
        ret_str = (
            ""
            if ret_rust in ["void", "c_void"] and not func.ret_type.is_pointer
            else f" -> {ret_rust}"
        )

        self.emit(f"pub fn {name}({', '.join(params)}){ret_str} {{", 1)
        call = f"unsafe {{ sys::{func.name}({', '.join(call_args)}) }}"

        if func.ret_type.name in self.handle_types and not func.ret_type.is_pointer:
            self.emit(f"{self.name_map[func.ret_type.name]}({call})", 2)
        elif func.ret_type.name in self.name_map and not func.ret_type.is_pointer:
            self.emit(f"unsafe {{ std::mem::transmute({call}) }}", 2)
        else:
            self.emit(call, 2)
        self.emit("}", 1)

    def generate(self) -> str:
        self.output = [
            "// This file is @generated by Rafx's bindings generator; DO NOT MODIFY, open an issue in https://github.com/zeozeozeo/rafx/issues instead",
            "#![allow(non_snake_case, non_camel_case_types, non_upper_case_globals, unused)]",
            "use std::ffi::c_void; use std::os::raw::c_char;",
            "",
        ]
        self.generate_sys_module()
        self.emit()
        self.generate_safe_typedefs()
        self.generate_safe_enums()
        self.generate_safe_structs_and_handles()
        self.generate_functions()
        return "\n".join(self.output)
