from os.path import commonpath
import json

from _ctypes import Structure
from pathlib import Path
import copy
from typing import Any, List
from dataclasses import dataclass, field
import re

from collections import deque

from collections import defaultdict
import heapq


'''
Почему у структуры два разных имени (oSSpawnNode и oTSpawnNode)?
Это классическое соглашение об именовании (Naming Convention) старой школы программирования:
oSSpawnNode (буква S означает Struct) — это внутреннее имя «тега» структуры.
oTSpawnNode (буква T означает Type) — это новое имя типа, созданное через typedef.
В своем C++ коде или плагинах разработчики Готики могут использовать имя oTSpawnNode как полноценный тип.

Binary Ninja базируется на Clang, 
а современные Си-компиляторы (включая Clang, GCC и MSVC) по умолчанию поддерживают анонимные структуры и объединения
в режиме C99 как повсеместное расширение языка (compiler extension).
'''


# @TODO: в zTypes3d появляется анонимная структура struct {zVEC2 *texUVPtr[4];};



@dataclass
class Comment:
    string: str = ''

@dataclass
class Field:
    type: str = '' # can be "int", or "void*", or "SomeClass"
    type_template: list[Any] = field(default_factory=list) # FieldTemplate, can be "<type, type>", or "<type, value>"
    type_suffix: str = '' # can be "*", or "**", or "&"
    name: str = '' # variable name
    name_suffix: str = '' # can be "[4]"
    value: str = '' # can be " = 2", or " : 2"
    value_kind: str = ''  # "", "=" или ":"
    original_text: str = ''

@dataclass
class FieldTemplate:
    type: str = '' # can be "int", or "void*", or "SomeClass"
    type_template: list[Any] = field(default_factory=list) # FieldTemplate, can be "<type, type>", or "<type, value>"
    type_suffix: str = '' # can be "*", or "**", or "&"
    value: str = ""

@dataclass
class Struct:
    name: str = 'anonymous'
    size: int = 0
    is_class: bool = False
    base_type: str = ''
    type: str = ''
    true_type: str = ''
    parent_list: list[str] = field(default_factory=list)
    is_vtable: bool = False
    field_list: list[Any] = field(default_factory=list)
    template_param_list: list[str] = field(default_factory=list)
    header: str = ''
    dependency_set: set[str] = field(default_factory=set)
    pack: str = ''
    virtual_function_list: list[Any] = field(default_factory=list)

@dataclass
class EnumItem:
    name: str = ''
    value: str = ''

@dataclass
class Enum:
    name: str = 'anonymous'
    is_typedef: bool = False
    typedef_name: str = ''
    type: str = ''
    is_class: bool = False
    base_type: str = ''
    item_list: list[EnumItem] = field(default_factory=list)

@dataclass
class PreprocessorDirective:
    text: str = ''

@dataclass
class VirtualFunction:
    name: str = ''
    conv_call: str = ''
    return_type: str = ''
    argument_string: str = ''
    name_space: str = ''


current_file_path = Path(__file__).resolve()
current_file_folder = current_file_path.parent
HEADER_FOLDER_PATH = current_file_folder / 'headers' / 'API'

header_list = [] #  'zContainer', 'zString', 'zVob'
ordered_header_list = []
header_dependency_dict = {}
# FILE_PATH = Path(r'C:\Users\user\PycharmProjects\bin_nin_export_parser\headers\API\zObject.h')


ANON_NANE = 'anonymous'
default_vtable_field = Field(type='void', type_suffix='**', name='vtable')
struct_dict = dict()
header_struct_dict = dict()
template_struct_dict = dict()
generated_struct_dict = dict()
extra_generated_struct_dict = dict()
enum_dict = dict()
global_field_list = list()
struct_dependency_solved = list()


def fix_string_for_parse(string):
    string = string.split('//', 1)[0].strip()

    if ':' in string:
        string = string.replace(':', ' : ')
        string = string.replace(' :  : ', '::')

    if ';' in string:
        string = string.replace(';', ' ; ')

    # zTRayTurboValMap<zCPolygon*, int>affectedPolyMap;
    if '>' in string:
        string = string.replace('>', '> ')

    for i in range(8):
        string = string.replace('\t', '')

    for i in range(8):
        string = string.replace('  ', ' ')

    string = string.replace(' ::', '::')
    string = string.replace('\t::', '::')

    return string


def parse_for_annonce(line):
    word_list = line.split()
    if len(word_list) < 2:
        return None

    extra_word = word_list[0].lower()
    if 'typedef' in extra_word:
        word_list = word_list[1:]

    type_ = ''
    struct_type = word_list[0].lower()
    if struct_type == 'class':
        type_ = 'struct'
    elif struct_type == 'struct':
        type_ = 'struct'
    elif struct_type == 'union':
        type_ = 'union'
    else:
        return None

    if '{' in word_list[-1]:
        word_list = word_list[:-1]

    struct = Struct()
    struct.type = type_
    struct.true_type = struct_type
    if len(word_list) == 1:
        pass # anonim
    elif len(word_list) == 2:
        struct.name = word_list[1]
    elif len(word_list) > 3 and word_list[2] == ':':
        struct.name = word_list[1]
        for other in word_list[3:]:
            if other not in ['public']:
                other = other.replace(',', '').strip()
                struct.parent_list.append(other)

    # print(struct)

    return struct


def parse_for_annonce_after(line):
    close_index = line.find('}')
    if close_index == -1:
        return ''

    end_index = line.find(';')
    if close_index == -1:
        return ''

    if end_index < close_index:
        return ''

    line = copy.copy(line).replace('}', '} ')
    word_list = line.split()
    if len(word_list) != 3:
        return ''

    struct_name = word_list[1].strip()

    return struct_name


def parse_for_enum(line):
    """
    Парсит объявления вида:
        enum Color { RED, GREEN };
        enum { RED, GREEN };
        enum Color : int { RED, GREEN };
        enum class Color { RED, GREEN };
        enum class Color : unsigned int { RED, GREEN };
    """
    if '{' not in line:
        return None

    word_list = line.split()

    is_typedef = False
    if 'typedef' in word_list:
        word_list = word_list[1:]
        is_typedef = True

    if len(word_list) < 2 or word_list[0].lower() != 'enum':
        return None

    enum_obj = Enum()
    enum_obj.is_typedef = is_typedef
    idx = 1

    # enum class ...
    if idx < len(word_list) and word_list[idx].lower() == 'class':
        enum_obj.is_class = True
        idx += 1

    # Имя enum, если оно есть.
    if idx < len(word_list) and word_list[idx] not in (':', '{', '}', ';', 'class'):
        enum_obj.name = word_list[idx]
        idx += 1

    # Базовый тип, если есть.
    if idx < len(word_list) and word_list[idx] == ':':
        idx += 1
        base_tokens = []
        while idx < len(word_list) and word_list[idx] not in ('{', '}', ';'):
            base_tokens.append(word_list[idx])
            idx += 1

        if base_tokens:
            enum_obj.base_type = ' '.join(base_tokens)

    return enum_obj


def parse_for_enum_item(line):
    """
    Парсит элементы enum:
        RED,
        GREEN = 1,
        BLUE = 2
        RED, GREEN, BLUE
        RED = 0, GREEN = 1, BLUE = 2
    """
    if not line:
        return []

    line = line.strip()

    if line.endswith(';'):
        line = line[:-1].strip()

    # Если всё в одной строке: enum Color { RED, GREEN, BLUE };
    if '{' in line and '}' in line:
        left = line.find('{')
        right = line.rfind('}')

        if right > left:
            line = line[left + 1:right]
        else:
            return []

    # Убираем возможные фигурные скобки и точки с запятой.
    line = line.replace('{', ' ')
    line = line.replace('}', ' ')
    line = line.replace(';', ' ')
    line = line.strip()

    if not line:
        return []

    items = []

    for part in line.split(','):
        part = part.strip()

        if not part:
            continue

        if part in (':', '=', 'class', 'enum', 'struct', 'public', 'private', 'protected'):
            continue

        if '=' in part:
            name, value = part.split('=', 1)
            name = name.strip()
            value = value.strip()
        else:
            name = part
            value = ''

        if not name:
            continue

        items.append(EnumItem(name=name, value=value))

    return items


def parse_for_field(line):
    # Филды не должны содержать фигурные скобки.
    if '{' in line or '}' in line:
        return None

    word_list = line.split()
    if len(word_list) < 3:
        return None

    if ';' != word_list[-1]:
        return None

    word_list = word_list[:-1]

    if '(' in line and ')' in line:
        return None

    # if word_list[0] == 'static':
    #     return None

    value = ''
    if ':' in word_list[-2]:
        value = word_list[-1]
        word_list = word_list[:-2]

    tp = ' '.join(word_list[:-1])
    # if tp == 'T*':
    #     tp = 'void*'

    fld = Field()
    fld.name = word_list[-1]
    fld.value = value
    fld.type = tp

    if '=' in line:
        print('WARNING!!! "=" in struct field')

    #print(fld)

    return fld


def parse_cpp_field(raw: str):
    """
    Парсит одно C++ поле класса/структуры.

    Примеры:
        parse_cpp_field("int a")
        parse_cpp_field("void* p")
        parse_cpp_field("const std::string & s = \"abc\"")
        parse_cpp_field("std::vector<int> v = {}")
        parse_cpp_field("std::map<std::string, std::vector<int>*> m")
        parse_cpp_field("int x : 3")
        parse_cpp_field("char name[10]")
    """

    def remove_comments(text: str) -> str:
        res: List[str] = []
        i = 0
        n = len(text)
        in_str = False
        in_char = False

        while i < n:
            ch = text[i]

            if in_str:
                res.append(ch)
                if ch == "\\" and i + 1 < n:
                    res.append(text[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    in_str = False
                i += 1
                continue

            if in_char:
                res.append(ch)
                if ch == "\\" and i + 1 < n:
                    res.append(text[i + 1])
                    i += 2
                    continue
                if ch == "'":
                    in_char = False
                i += 1
                continue

            if ch == '"':
                in_str = True
                res.append(ch)
                i += 1
                continue

            if ch == "'":
                in_char = True
                res.append(ch)
                i += 1
                continue

            if ch == "/" and i + 1 < n:
                if text[i + 1] == "/":
                    while i < n and text[i] != "\n":
                        i += 1
                    continue

                if text[i + 1] == "*":
                    i += 2
                    while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                        i += 1
                    i += 2
                    continue

            res.append(ch)
            i += 1

        return "".join(res)

    # Филды не должны содержать фигурные скобки.
    if '{' in raw or '}' in raw:
        return None

    word_list = raw.split()
    if len(word_list) < 3:
        return None

    if ';' != word_list[-1]:
        return None

    word_list = word_list[:-1]

    if '(' in raw or ')' in raw:
        return None

    # if word_list[0] == 'static':
    #     return None

    original_text = raw.replace(' ;', ';').strip()

    if raw.count('<') > 1 and 'const' not in raw and '<<=' not in raw:
        print(f'WARNING!!! multiple "<" in struct field {raw}')

    raw = remove_comments(raw).strip()
    if raw.endswith(";"):
        raw = raw[:-1].strip()

    def find_value_separator(text: str):
        angle = bracket = paren = 0
        i = 0
        n = len(text)

        while i < n:
            ch = text[i]

            if ch == "<":
                angle += 1
            elif ch == ">":
                if angle > 0:
                    angle -= 1
            elif ch == "[":
                bracket += 1
            elif ch == "]":
                if bracket > 0:
                    bracket -= 1
            elif ch == "(":
                paren += 1
            elif ch == ")":
                if paren > 0:
                    paren -= 1
            elif ch == "=" and angle == bracket == paren == 0:
                return i
            elif ch == ":" and angle == bracket == paren == 0:
                if i + 1 < n and text[i + 1] == ":":
                    i += 2
                    continue
                if i > 0 and text[i - 1] == ":":
                    i += 1
                    continue
                return i

            i += 1

        return None

    sep = find_value_separator(raw)
    if sep is not None:
        left = raw[:sep].strip()
        value_part = raw[sep:].strip()
        value_kind = value_part[0] if value_part and value_part[0] in "=:" else ""
        value = value_part[1:].strip() if value_kind else value_part
    else:
        left = raw
        value = ""
        value_kind = ""

    def find_first_top_level_bracket(text: str):
        angle = 0
        for i, ch in enumerate(text):
            if ch == "<":
                angle += 1
            elif ch == ">":
                if angle > 0:
                    angle -= 1
            elif ch == "[" and angle == 0:
                return i
        return None

    def find_name(text: str):
        matches = list(re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", text))
        if not matches:
            return None, "", ""

        idx = len(matches) - 1
        trailing = []

        while idx >= 0 and matches[idx].group() in {"const", "volatile", "mutable"}:
            trailing.insert(0, matches[idx].group())
            idx -= 1

        if idx < 0:
            return None, "", ""

        m = matches[idx]
        return m.start(), m.group(), " ".join(trailing)

    bracket_pos = find_first_top_level_bracket(left)

    if bracket_pos is not None:
        j = bracket_pos - 1
        while j >= 0 and left[j].isspace():
            j -= 1

        end = j + 1
        while j >= 0 and (left[j].isalnum() or left[j] == "_"):
            j -= 1
        j += 1

        if end > j:
            name = left[j:end]
            name_start = j
        else:
            name_start, name, _ = find_name(left)
            name_start = name_start or 0

        name_suffix = left[bracket_pos:].strip()
        name_suffix = re.sub(r"\s*([]])\s*(\[)", r"\1\2", name_suffix)
        type_part = left[:name_start].strip()
    else:
        name_start, name, trailing = find_name(left)
        if name_start is None:
            return Field(
                type=left,
                value=value,
                value_kind=value_kind,
            )

        name_suffix = ""
        prefix = left[:name_start].strip()
        type_part = (prefix + " " + trailing).strip() if trailing else prefix

    def split_suffix(t: str):
        t = t.strip()
        if not t:
            return "", ""

        cv = []
        suffix_chars = []
        suffix_start = len(t)
        i = len(t) - 1

        def skip_spaces(pos: int) -> int:
            while pos >= 0 and t[pos].isspace():
                pos -= 1
            return pos

        while True:
            i = skip_spaces(i)
            if i < 0:
                break

            ch = t[i]

            if ch in "*&":
                suffix_chars.insert(0, ch)
                suffix_start = i
                i -= 1

            elif ch.isalnum() or ch == "_":
                j = i
                while j >= 0 and (t[j].isalnum() or t[j] == "_"):
                    j -= 1

                word = t[j + 1:i + 1]
                if word in {"const", "volatile", "mutable"}:
                    cv.insert(0, word)
                    suffix_start = j + 1
                    i = j
                else:
                    break
            else:
                break

        if not suffix_chars and not cv:
            return t, ""

        base = t[:suffix_start].strip()
        suffix = "".join(suffix_chars)

        if cv:
            base = (base + " " + " ".join(cv)).strip() if base else " ".join(cv)

        return base, suffix

    def is_cv_only(s: str) -> bool:
        s = s.strip()
        if not s:
            return True
        return bool(
            re.fullmatch(
                r"(?:const|volatile|mutable)(?:\s+(?:const|volatile|mutable))*",
                s,
            )
        )

    def split_top_level_commas(text: str):
        parts = []
        start = 0
        angle = bracket = paren = 0
        in_str = False
        in_char = False

        i = 0
        n = len(text)

        while i < n:
            ch = text[i]

            if in_str:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == '"':
                    in_str = False
                i += 1
                continue

            if in_char:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "'":
                    in_char = False
                i += 1
                continue

            if ch == '"':
                in_str = True
                i += 1
                continue

            if ch == "'":
                in_char = True
                i += 1
                continue

            if ch == "<":
                angle += 1
            elif ch == ">":
                if angle > 0:
                    angle -= 1
            elif ch == "[":
                bracket += 1
            elif ch == "]":
                if bracket > 0:
                    bracket -= 1
            elif ch == "(":
                paren += 1
            elif ch == ")":
                if paren > 0:
                    paren -= 1
            elif ch == "," and angle == bracket == paren == 0:
                parts.append(text[start:i].strip())
                start = i + 1

            i += 1

        parts.append(text[start:].strip())
        return [p for p in parts if p]

    def is_literal(arg: str) -> bool:
        a = arg.strip()
        if not a:
            return False

        if re.fullmatch(
            r"[+-]?(0[xXbBoO][A-Za-z0-9_]+|\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d)?)([uUlLfF]*)?",
            a,
        ):
            return True

        if re.fullmatch(r'"(?:[^"\\]|\\.)*"', a):
            return True

        if re.fullmatch(r"'(?:[^'\\]|\\.)'", a):
            return True

        return a in {"true", "false", "nullptr", "NULL"}

    def parse_template_arg(arg: str) -> FieldTemplate:
        arg = arg.strip()
        if not arg:
            return FieldTemplate()

        if is_literal(arg):
            return FieldTemplate(type=arg, value=arg)

        lt = arg.find("<")
        if lt > 0:
            depth = 0
            gt = -1

            for i in range(lt, len(arg)):
                if arg[i] == "<":
                    depth += 1
                elif arg[i] == ">":
                    depth -= 1
                    if depth == 0:
                        gt = i
                        break

            if gt != -1:
                base = arg[:lt].strip()
                inner = arg[lt + 1:gt].strip()
                after = arg[gt + 1:].strip()

                after_base, suffix = split_suffix(after)

                if after_base and not is_cv_only(after_base):
                    # Выражения вроде std::numeric_limits<int>::max()
                    # храним сырыми в value, чтобы не ломать тип.
                    if after_base.startswith("::") and "(" not in after and ")" not in after:
                        return FieldTemplate(type=arg)
                    return FieldTemplate(type=arg, value=arg)

                if after_base:
                    base = (base + " " + after_base).strip()

                return FieldTemplate(
                    type=base,
                    type_template=parse_template_args(inner),
                    type_suffix=suffix,
                )

        base, suffix = split_suffix(arg)
        return FieldTemplate(type=base, type_suffix=suffix)

    def parse_template_args(inner: str) -> List[FieldTemplate]:
        inner = inner.strip()
        if not inner:
            return []
        return [parse_template_arg(p) for p in split_top_level_commas(inner)]

    lt = type_part.find("<")
    if lt > 0:
        depth = 0
        gt = -1

        for i in range(lt, len(type_part)):
            if type_part[i] == "<":
                depth += 1
            elif type_part[i] == ">":
                depth -= 1
                if depth == 0:
                    gt = i
                    break

        if gt != -1:
            base = type_part[:lt].strip()
            inner = type_part[lt + 1:gt].strip()
            after = type_part[gt + 1:].strip()

            after_base, suffix = split_suffix(after)

            if after_base and not is_cv_only(after_base):
                base = type_part
                suffix = ""
                type_template: List[FieldTemplate] = []
            else:
                if after_base:
                    base = (base + " " + after_base).strip()
                type_template = parse_template_args(inner)
        else:
            base, suffix = split_suffix(type_part)
            type_template = []
    else:
        base, suffix = split_suffix(type_part)
        type_template = []

    return Field(
        type=base,
        type_template=type_template,
        type_suffix=suffix,
        name=name,
        name_suffix=name_suffix,
        value=value,
        value_kind=value_kind,
        original_text=original_text
    )


def parse_for_preprocessor_directive(line: str):
    command = line.strip()
    command = command.split('//')[0]

    if not command.startswith('#'):
        return None

    is_needed_command = False
    for cmd in ['pragma']:
        if cmd in command:
            is_needed_command = True
            break

    if not is_needed_command:
        return None

    return command


def parse_for_virtual_method(line: str):
    #     virtual zCClassDef* _GetClassDef( void ) const                      zCall( 0x00401EC0 );
    #     virtual void Archive( zCArchiver& )                                 zCall( 0x00401ED0 );
    #     virtual void Unarchive( zCArchiver& )                               zCall( 0x00401EE0 );
    #     virtual ~zCObject( void )                                           zCall( 0x005A8C50 );

    line = line.split('zCall')[0]
    open_bracket_index = line.find('(')
    close_bracket_index = line.find(')')
    if open_bracket_index == -1 or close_bracket_index == -1:
        print(f'WARNING: wrong function signature: "{line}"')
        return None

    argument_string = line[open_bracket_index + 1:close_bracket_index]
    argument_string = argument_string.replace(' ', '').strip()
    if argument_string == 'void':
        argument_string = ''

    conv_call = '__thiscall' # different conv_call = defferent function
    if '__thiscall' in line:
        conv_call = '__thiscall'
    elif '__fastcall' in line:
        conv_call = '__fastcall'
    elif '__cdecl' in line:
        conv_call = '__cdecl'
    elif '__stdcall' in line:
        conv_call = '__stdcall'

    return_type = ''
    function_name = line[:open_bracket_index].strip()
    function_name = function_name.replace('virtual', '').strip()
    function_name = function_name.replace('const', '').strip()
    function_name = function_name.replace(' *', '*').strip()
    function_name = function_name.replace('*', '* ').strip()

    function_name = function_name.replace('__thiscall', '').strip()
    function_name = function_name.replace('__fastcall', '').strip()
    function_name = function_name.replace('__cdecl', '').strip()
    function_name = function_name.replace('__stdcall', '').strip()

    function_name = function_name.replace('  ', ' ').strip()
    function_name = function_name.replace('  ', ' ').strip()

    function_name = function_name.replace(' *', '*').strip()
    function_name = function_name.replace(' &', '&').strip()

    function_name_splited = function_name.split()
    if len(function_name_splited) == 1:
        if function_name_splited[0].startswith('~'):
            return_type = 'void*'
            function_name = 'destructor'
        else:
            print(f'WARNING: wrong function_name: "{function_name}"')
    elif len(function_name_splited) == 2:
        return_type = function_name_splited[0]
        function_name = function_name_splited[1]
    elif len(function_name_splited) == 3:
        return_type = function_name_splited[0] + ' ' + function_name_splited[1]
        function_name = function_name_splited[2]
    else:
        print(f'WARNING: wrong function_name: "{function_name}"')

    return_type = return_type.strip()
    function_name = function_name.strip()

    if not return_type or not function_name:
        print(f'WARNING: wrong function signature: "{line}"')
        return None

    # print(f'{return_type=}, {function_name=}')

    virtual_function = VirtualFunction(name=function_name, conv_call=conv_call,
                                       return_type=return_type, argument_string=argument_string)

    return virtual_function


def parse_template(template):
    if not len(template):
        print(f'WARNING!!! WRONG TEMPLATE {template}')
        return []

    template_part_list = template.replace('>', '').split('<')
    if len(template_part_list) != 2:
        print(f'WARNING!!! WRONG TEMPLATE {template}')
        return []

    template_param_list = []
    template_body_part_list = template_part_list[1].split(',')
    for template_body_part in template_body_part_list:
        template_body_param_part_list = template_body_part.strip().split()
        if len(template_body_param_part_list) != 2:
            print(f'WARNING!!! WRONG TEMPLATE {template}')
            return []

        template_param_list.append(template_body_param_part_list[1].strip())

    # print(f'parsed template "{template}" -> {template_param_list}')

    return template_param_list


def parse_header(header_file_path):
    if not header_file_path.exists():
        return

    text = header_file_path.read_text()
    if len(text) < 4:
        return

    line_list = text.splitlines()
    if len(line_list) < 1:
        return

    header_name = header_file_path.stem
    comm = Comment()
    comm.string = header_name
    struct_dict[f'header_name: {header_name}'] = comm

    struct_in_depth_dict = {0: None}
    enum_in_depth_dict = {0: None}
    depth = 0

    def close_struct_at_depth(current_depth, line_num):
        if current_depth in struct_in_depth_dict and struct_in_depth_dict[current_depth]:
            struct_obj = struct_in_depth_dict[current_depth]
            # print(f'close struct [{current_depth}] with name {struct_obj.name} at line {line_num}')

            depth_up = current_depth - 1

            if len(header_name):
                struct_obj.header = header_name

            if depth_up in struct_in_depth_dict and struct_in_depth_dict[depth_up]:
                # если струкрту с именем - то она не занимает место в памати структуры
                # struct_in_depth_dict[depth_up].field_list.append(struct_obj)
                if struct_obj.name == 'anonymous':
                    struct_in_depth_dict[depth_up].field_list.append(struct_obj)
                else:
                    struct_dict[struct_obj.name] = struct_obj
            else:
                struct_dict[struct_obj.name] = struct_obj

            struct_in_depth_dict[current_depth] = None

    def close_enum_at_depth(current_depth, line_num):
        if current_depth in enum_in_depth_dict and enum_in_depth_dict[current_depth]:
            enum_obj = enum_in_depth_dict[current_depth]

            if 'VolatileOverflowMode' in enum_obj.name or 'VolatileOverflowMode' in enum_obj.typedef_name:
                pass

            # print(f'close enum [{current_depth}] with name {enum_obj.name} at line {line_num}')

            depth_up = current_depth - 1

            enum_obj_name = enum_obj.name
            if enum_obj.name == ANON_NANE and enum_obj.is_typedef and enum_obj.typedef_name:
                enum_obj_name = enum_obj.typedef_name

            # Если enum внутри struct, кладём его внутрь struct.
            if depth_up in struct_in_depth_dict and struct_in_depth_dict[depth_up]:
                struct_in_depth_dict[depth_up].field_list.append(enum_obj)
            else:
                # Иначе это top-level enum.
                enum_dict[enum_obj_name] = enum_obj

            # дублируем в глобал, мб переделать надо, не уверен
            enum_dict[enum_obj_name] = enum_obj

            enum_in_depth_dict[current_depth] = None

    pack = ''
    template = ''
    size = 0
    template_line = 0
    for i, line in enumerate(line_list):
        line_num = i + 1

        if 'friend' in line:
            continue

        if 'zoneActiveHandle' in line:
            pass

        # // sizeof 04h    offset 38h
        if 'sizeof' in line:
            line_prts = line.strip().split()
            if len(line_prts) == 3 and line_prts[1] == 'sizeof' and 'h' in line_prts[2]:
                try:
                    size = int(line_prts[2][:-1], 16)
                except:
                    pass

        line = fix_string_for_parse(line)

        if len(line) < 1:
            continue

        is_struct_annonce = False
        is_enum_annonce = False

        if 'template' in line:
            template = line.strip()
            template_line = i

        # enum
        enum_obj = parse_for_enum(line)
        if enum_obj:
            # print(f'open enum [{depth}] {enum_obj.name} at line {line_num}')
            enum_in_depth_dict[depth] = enum_obj
            is_enum_annonce = True

            # Поддерживаем однострочный enum:
            # enum Color { RED, GREEN, BLUE };
            if '{' in line and '}' in line:
                items = parse_for_enum_item(line)
                if items:
                    # print(
                    #     f'add enum items '
                    #     f'{[item.name for item in items]} '
                    #     f'to enum {enum_obj.name} '
                    #     f'at line {line_num}'
                    # )
                    enum_obj.item_list.extend(items)

        # struct / class
        struct_obj = parse_for_annonce(line)
        if struct_obj:
            if 'zCObjectFactory' in line:
                pass

            if len(template) and template_line == i - 1:
                parsed_template = parse_template(template)
                if len(parsed_template):
                    struct_obj.template_param_list = parsed_template
                else:
                    print(f'WARNING!!! CANT PARSE TEMPLATE FROM STRUCT {struct_obj}')
                template = ''

            if size > 0:
                struct_obj.size = size
                size = 0

            if pack:
                struct_obj.pack = pack

            if struct_obj.true_type == 'class':
                parent_strcut = struct_in_depth_dict.get(depth - 1, None)
                if parent_strcut and len(parent_strcut.name) and parent_strcut.true_type == 'class':
                    struct_obj.name = f'{parent_strcut.name}_{struct_obj.name}'

            # print(f'open struct [{depth}] {struct_obj.name} at line {line_num}')
            struct_in_depth_dict[depth] = struct_obj
            is_struct_annonce = True

        clse_name = parse_for_annonce_after(line)
        if len(clse_name) and (depth - 1) in struct_in_depth_dict:
            closed_struct = struct_in_depth_dict[depth - 1]
            if isinstance(closed_struct, Struct) and closed_struct.name != 'anonymous':
                closed_struct_copy = copy.deepcopy(closed_struct)
                closed_struct_copy.name = clse_name
                struct_dict[closed_struct_copy.name] = closed_struct_copy


        preprocessor_directive = parse_for_preprocessor_directive(line)
        if preprocessor_directive:
            if 'pack' in preprocessor_directive:
                if 'push' in preprocessor_directive:
                    pack = preprocessor_directive
                elif 'pop' in preprocessor_directive:
                    pack = ''

            # struct_in_depth_dict[depth - 1].field_list.append(preprocessor_directive)


        # Поля и элементы enum разбираем только если текущая строка не сама объявление.
        if not is_struct_annonce and not is_enum_annonce:
            # Обычное поле внутри struct.
            fld = parse_cpp_field(line)
            if fld:
                if struct_in_depth_dict.get(depth - 1) and not enum_in_depth_dict.get(depth - 1):
                    # print(
                    #     f'add field {fld.name} '
                    #     f'to struct {struct_in_depth_dict[depth - 1].name} '
                    #     f'at line {line_num}'
                    # )
                    # print(f'{line} -> {fld}')

                    # if 'zCBolt' in line:
                    #     pass
                    #     if len(fld.type_template):
                    #         pass
                    #         parent_structure = struct_in_depth_dict.get(depth - 1)
                    #         for type_template in fld.type_template:
                    #             if type_template.type == 'zCBolt':
                    #                 type_template.type = parent_structure.name

                    if 'static' not in fld.type:
                        struct_in_depth_dict[depth - 1].field_list.append(fld)
                else:
                    if depth - 1 == 0 and 'enum' not in line and 'return' not in line and 'extern' not in line:
                        global_field_list.append(fld)


            # Элементы enum.
            if enum_in_depth_dict.get(depth - 1):
                items = parse_for_enum_item(line)
                if items:
                    # print(
                    #     f'add enum items '
                    #     f'{[item.name for item in items]} '
                    #     f'to enum {enum_in_depth_dict[depth - 1].name} '
                    #     f'at line {line_num}'
                    # )

                    if 'VolatileOverflowMode' in enum_in_depth_dict.get(depth - 1).name or 'VolatileOverflowMode' in enum_in_depth_dict.get(depth - 1).typedef_name:
                        pass
                    annonce_after = parse_for_annonce_after(line)
                    if not annonce_after:
                        enum_in_depth_dict[depth - 1].item_list.extend(items)
                    else:
                        if enum_in_depth_dict[depth - 1].is_typedef:
                            enum_in_depth_dict[depth - 1].typedef_name = annonce_after
                        else:
                            enum_in_depth_dict[depth - 1].name = annonce_after

        # Виртуальные методы.
        if 'virtual' in line:
            if struct_in_depth_dict.get(depth - 1):
                struct_in_depth_dict[depth - 1].is_vtable = True
                virtual_function = parse_for_virtual_method(line)
                if virtual_function is not None:
                    name_space = struct_in_depth_dict[depth - 1].name
                    virtual_function.name_space = name_space
                    struct_in_depth_dict[depth - 1].virtual_function_list.append(virtual_function)

        depth_delta = line.count('{') - line.count('}')
        depth += depth_delta

        # Закрытие struct / enum.
        if depth_delta < 0:
            close_struct_at_depth(depth, line_num)
            close_enum_at_depth(depth, line_num)

        # Поддержка однострочных объявлений:
        # enum Color { RED, GREEN };
        # struct A { int x; };
        elif depth_delta == 0 and '{' in line and '}' in line and (is_struct_annonce or is_enum_annonce):
            close_struct_at_depth(depth, line_num)
            close_enum_at_depth(depth, line_num)


def start_parse():
    if len(header_list):
        for header in header_list:
            header_file_path = HEADER_FOLDER_PATH / (header + '.h')
            parse_header(header_file_path)
    else:
        if len(ordered_header_list):
            for header in ordered_header_list:
                header_file_path = HEADER_FOLDER_PATH / (header + '.h')
                parse_header(header_file_path)
        else:
            for header in HEADER_FOLDER_PATH.rglob('*.h'):
                parse_header(header)


def add_missing():
    # globals
    global_field_list.append(Field(type='const float', name='PI', value_kind='=', value='3.14'))
    global_field_list.append(Field(type='const float', name='DEGREE', value_kind='=', value='57.3'))
    global_field_list.append(Field(type='const float', name='FLT_MAX', value_kind='=', value='3.402823466e+38f'))
    global_field_list.append(Field(type='const float', name='FLT_MIN', value_kind='=', value='-3.402823466e+38f'))
    global_field_list.append(Field(type='const float', name='INFINITE', value_kind='=', value='1.0f / 0.0f'))
    global_field_list.append(Field(type='const int', name='RAND_MAX', value_kind='=', value='0x7FFF'))

    global_field_list.append(Field(type='const unsigned int', name='NPC_PERC_MAX', value_kind='=', value='33'))

    enum = Enum(name='zTStaticIntersectionTest', item_list=[EnumItem(name='StaticIntersection1'), EnumItem(name='StaticIntersection2')])
    enum_dict[enum.name] = enum

    enum = Enum(name='zTDynamicIntersectionTest', item_list=[EnumItem(name='DynamicIntersection1'), EnumItem(name='DynamicIntersection2')])
    enum_dict[enum.name] = enum

    enum = Enum(name='zTVisualCamAlign', item_list=[EnumItem(name='VisualCamAlign1'), EnumItem(name='VisualCamAlign2')])
    enum_dict[enum.name] = enum


def add_inheritance_and_vtable():
    def create_and_add_vtable_for_struct(strct):
        vtable_struct = Struct(name=f'{strct.name}_vtable')
        for vfunc in strct.virtual_function_list:
            # name: str = ''
            # conv_call: str = ''
            # return_type: str = ''
            # argument_string: str = ''
            pass
            vtable_struct.field_list.append(Field(type=vfunc.return_type, name=vfunc.name))

        vtable_field = Field(type=vtable_struct.name, type_suffix='*', name='vtable')
        strct.field_list.insert(0, vtable_field)
        strct.dependency_set.add(vtable_struct.name)

        struct_dict[vtable_struct.name] = vtable_struct

        print(vtable_struct)

    def recursive_vtable_setup(strct, strct_name, virtual_function_list) -> bool:
        if not len(strct.parent_list):
            if strct.is_vtable:
                if len(strct.field_list):
                    if 'vtable' not in strct.field_list[0].name:
                        create_and_add_vtable_for_struct(strct)
                else:
                    create_and_add_vtable_for_struct(strct)

                return True

            return False
        else:
            is_vtable_parent = False
            is_vtable_this = False
            for struct_name in strct.parent_list:
                if struct_name not in struct_dict:
                    continue

                parent_struct = struct_dict[struct_name]
                is_vtable = recursive_vtable_setup(parent_struct)
                if is_vtable:
                    is_vtable_parent = True
                else:
                    if strct.is_vtable:
                        if len(strct.field_list):
                            if 'vtable' not in strct.field_list[0].name:
                                create_and_add_vtable_for_struct(strct)
                        else:
                            create_and_add_vtable_for_struct(strct)

                        is_vtable_this = True

            if is_vtable_parent or is_vtable_this:
                return True

            return False

    for struct in list(struct_dict.values()):
        if not isinstance(struct, Struct):
            continue

        for struct_parent_name in reversed(list(struct.parent_list)):
            if struct_parent_name not in struct_dict:
                continue

            parent_struct = copy.deepcopy(struct_dict[struct_parent_name])
            parent_struct.name = f'{struct_parent_name}_for_{struct.name}'
            struct_dict[parent_struct.name] = parent_struct

            struct.parent_list.remove(struct_parent_name)
            struct.parent_list.append(parent_struct.name)

            base_field = Field(type=parent_struct.name, name=f'base_{struct_parent_name}')
            struct_dict[struct.name].field_list.insert(0, base_field)

    # for struct in list(struct_dict.values()):
    #     if isinstance(struct, Struct):
    #         recursive_vtable_setup(struct, struct.name, struct.virtual_function_list)


def set_personal_inheritance():
    def clean_parent_name(name):
        if isinstance(name, str) and "_for_" in name:
            return name.split("_for_", 1)[0]
        return name

    # Сохраняем исходные структуры до изменений.
    # Это нужно, чтобы при обработке zCMusic не копировать уже изменённый zCResource.
    original_structs = {}
    for name, st in list(struct_dict.items()):
        if not isinstance(st, Struct) or "_for_" in name:
            continue

        st = copy.deepcopy(st)
        st.name = name

        # Если parent_list уже был испорчен предыдущим запуском,
        # возвращаем исходные имена родителей.
        st.parent_list = [clean_parent_name(p) for p in st.parent_list]

        # Убираем ранее созданные base-поля, чтобы они не дублировались.
        base_field_names = {f"base_{p}" for p in st.parent_list}
        st.field_list = [
            f for f in st.field_list
            if getattr(f, "name", None) not in base_field_names
        ]

        original_structs[name] = st

    # Удаляем старые сгенерированные *_for_* структуры.
    for name in list(struct_dict.keys()):
        if isinstance(struct_dict.get(name), Struct) and "_for_" in name:
            del struct_dict[name]

    def apply_base_fields(st, base_fields):
        """
        base_fields: список кортежей (type_name, field_name)
        Например:
            (
                ("zCObject_for_zCMusic", "base_zCObject"),
            )
        """
        if not base_fields:
            return

        field_names = {field_name for _, field_name in base_fields}

        # Убираем старые base-поля.
        st.field_list = [
            f for f in st.field_list
            if getattr(f, "name", None) not in field_names
        ]

        # Вставляем base-поля в начало, сохраняя порядок.
        for type_name, field_name in reversed(base_fields):
            st.field_list.insert(
                0,
                Field(type=type_name, name=field_name)
            )

    def make_personal(parent_name, top_name):
        """
        Создаёт уникальную копию parent_name для top_name:
            parent_for_top
        """
        personal_name = f"{parent_name}_for_{top_name}"

        if personal_name in struct_dict:
            return personal_name

        if parent_name not in original_structs:
            return None

        # Копируем из исходного определения, а не из уже изменённого.
        st = copy.deepcopy(original_structs[parent_name])
        st.name = personal_name

        # Регистрируем раньше, чтобы защититься от возможных циклов.
        struct_dict[personal_name] = st

        base_fields = []

        # У копии parent тоже должны быть свои базовые копии.
        # Например:
        #   zCResource_for_zCMusic
        #       base_zCObject -> zCObject_for_zCMusic
        for p in original_structs[parent_name].parent_list:
            if p not in original_structs:
                continue

            p_personal = make_personal(p, top_name)
            if p_personal is None:
                continue

            base_fields.append((p_personal, f"base_{p}"))

            st.parent_list.remove(p)
            st.parent_list.append(p_personal)

        apply_base_fields(st, base_fields)

        # В целевых структурах наследования уже нет.
        # Если твой генератору нужен parent_list, можно поставить сюда
        # список personal_parents, но тогда это зависит от твоего генератора.
        # st.parent_list = []


        return personal_name

    # Обработка исходных классов.
    for top_name, top_struct in list(original_structs.items()):
        st = copy.deepcopy(top_struct)
        st.name = top_name

        base_fields = []

        # У верхнего класса заменяем родителеня на его личную копию.
        # Например:
        #   zCMusic
        #       base_zCResource -> zCResource_for_zCMusic
        for p in top_struct.parent_list:
            if p not in original_structs:
                continue

            p_personal = make_personal(p, top_name)
            if p_personal is None:
                continue

            base_fields.append((p_personal, f"base_{p}"))

            st.parent_list.remove(p)
            st.parent_list.append(p_personal)

        apply_base_fields(st, base_fields)

        # Аналогично: в финальных структурах наследование заменено полями.
        # st.parent_list = []

        struct_dict[top_name] = st

    # Небольшой порядок вывода:
    # сначала базовый класс, потом его *_for_* копии, затем следующий класс.
    # Если порядок в struct_dict не важен, этот блок можно не использовать.
    ordered = {}

    for base_name in original_structs:
        if base_name in struct_dict:
            ordered[base_name] = struct_dict[base_name]

        for top_name in original_structs:
            personal_name = f"{base_name}_for_{top_name}"
            if personal_name in struct_dict:
                ordered[personal_name] = struct_dict[personal_name]

    # На всякий случай добавим остальные, если что-то осталось.
    for name, st in struct_dict.items():
        if name not in ordered:
            ordered[name] = st

    struct_dict.clear()
    struct_dict.update(ordered)


def create_all_template_variables():
    var_dict = {'zCArray': ['zSEvasionSearchDesc', 'zCCSCamera', 'unsignedshort', 'zSCtrlValue', 'zCActiveSnd',
                            'zCWaveData', 'unsignedchar', 'unsigned_char', 'zTBBox2D', 'zCCollisionReport',
                            'zTBinTreeNode', 'zCVertex', 'zCVertFeature', 'zCCombine', 'zCTexture', 'zMAT4',
                            'Vertex', 'Triangle', 'zTLazyMesh', 'zTWedgeColl', 'zCClassDef',
                            'zCVobLightPreset', 'zCTransferConstr', 'zCPatchMap', 'void', 'zSEnvValues', 'oCMission',
                            'oCNews', 'oCNpc', 'oCRtnEntry', 'oCVisualFX', 'zCMenu', 'zCVertexBuffer_D3D'],
                'zCArraySort': ['zCClassDef', 'zCMenu', 'zCMenuItem', 'zCActiveSnd', 'zCWaveData', 'zCPolygon',
                                'zTLightScore', 'TVertex3ds', 'zCLightMap', 'zCParticleEmitter', 'zCVertex'],
                'zCList': ['zVEC3', 'zCPlayerGroup', 'zCPolygon', 'oCVob', 'zCConsole', 'zCParserExternals',
                           'zCInputCallback', 'zCVobWaypoint', 'oCItemContainer'],
                'zCTree': ['',], }

    # ['zCArray', 'zCArraySort', 'zCArrayAdapt', 'zCTree', 'zList', 'zCList', 'zCListSort']

    for template_struct_name, struct_name_list in var_dict.items():
        if template_struct_name not in template_struct_dict:
            continue

        for param in struct_name_list:
            if not len(param):
                continue

            for param_var in [param, f'{param}*']:
                if param not in struct_dict:
                    continue

                if param_var in ['oCVisualFX*']:
                    continue

                template_struct = copy.deepcopy(template_struct_dict[template_struct_name])
                nts = create_dynamic_struct('', template_struct, None, [param_var], '', is_ret_gen=True)

                if nts.name not in struct_dict and nts.name not in generated_struct_dict:
                    extra_generated_struct_dict[nts.name] = nts
                # print(nts)


def set_vtable():
    def is_same_vtable_field(vf1, vf2):
        return (vf1.name == vf2.name and vf1.conv_call == vf2.conv_call
                and vf1.return_type == vf2.return_type and vf1.argument_string == vf2.argument_string)

    def is_virtual_function_list_contain_virtual_function(virtual_function_list, virtual_function):
        for i, vf in enumerate(virtual_function_list):
            if is_same_vtable_field(vf, virtual_function):
                return i

        return -1

    def create_and_add_vtable_for_struct(strct, virtual_function_list):
        if len(strct.field_list) and 'vtable' in strct.field_list[0].name:
            return

        is_generated_struct = True # '_for_' in strct.name
        if is_generated_struct:
            vtable_struct = Struct(name=f'{strct.name}_vtable', type='struct')
            strct.dependency_set.add(vtable_struct.name)

            uniq_virtual_function_list = []
            virtual_function_name_list = []
            for vfunc in virtual_function_list:
                index = is_virtual_function_list_contain_virtual_function(uniq_virtual_function_list, vfunc)
                if index == -1:
                    uniq_virtual_function_list.append(vfunc)
                else:
                    uniq_virtual_function_list[index] = vfunc


            for vfunc in uniq_virtual_function_list:
                name_space = f'{vfunc.name_space}_' if len(vfunc.name_space) else ''
                count = virtual_function_name_list.count(vfunc.name)
                count_text = ''
                if count > 0:
                    count_text = str(count + 1)
                name = f'(*{name_space}{vfunc.name}{count_text})()'

                return_type = vfunc.return_type
                if return_type == 'zCListSort<oCItem>*':
                    return_type = 'zCListSort_oCItem*'
                elif return_type == 'zCTree<zCVob>*':
                    return_type = 'zCTree_zCVob*'

                vtable_struct.field_list.append(Field(type=return_type, name=name))
                virtual_function_name_list.append(vfunc.name)

            vtable_field = Field(type=vtable_struct.name, type_suffix='*', name='vtable')
            strct.dependency_set.add(vtable_struct.name)
            struct_dict[vtable_struct.name] = vtable_struct
        else:
            vtable_field = Field(type=f'{strct.name}_vtable', type_suffix='**', name='vtable')

        strct.field_list.insert(0, vtable_field)
        # print(vtable_struct)

    def recursive_vtable_setup(strct, strct_name, virtual_function_list) -> bool:
        if not len(strct.parent_list):
            if strct.is_vtable:
                create_and_add_vtable_for_struct(strct, virtual_function_list)
                return True

            return False
        else:
            is_vtable_parent = False
            is_vtable_this = False
            for i, struct_name in enumerate(strct.parent_list):
                if struct_name not in struct_dict:
                    continue

                parent_struct = struct_dict[struct_name]
                if i == 0:
                    all_virtual_function_list = parent_struct.virtual_function_list + virtual_function_list
                else:
                    all_virtual_function_list = parent_struct.virtual_function_list
                is_vtable = recursive_vtable_setup(parent_struct, struct_name, all_virtual_function_list)
                if is_vtable:
                    is_vtable_parent = True
                else:
                    if strct.is_vtable:
                        create_and_add_vtable_for_struct(strct, all_virtual_function_list)
                        is_vtable_this = True

            if is_vtable_parent or is_vtable_this:
                return True

            return False

    for struct in list(struct_dict.values()):
        if isinstance(struct, Struct):
            if '_for_' not in struct.name:
                # if 'zCMusic' in struct.name:
                recursive_vtable_setup(struct, struct.name, struct.virtual_function_list)


def extract_template_struct():
    delete_key_list = []
    for struct in struct_dict.values():
        if not isinstance(struct, Struct):
            continue

        if not len(struct.template_param_list):
            continue

        template_struct_dict[struct.name] = copy.deepcopy(struct)
        delete_key_list.append(struct.name)

    for delete_key in delete_key_list:
        struct_dict.pop(delete_key, None)


def create_dynamic_struct(struct_name, template_struct, fld, container_param_list, suffix, is_ret_gen=False):
    if len(template_struct.template_param_list) != len(container_param_list):
        print(f'WARNING!!! len(template_struct.template_param_list) != container_param_list')
        return None

    clean_struct_name = template_struct.name
    for i in range(len(container_param_list)):
        clean_struct_name += '_' + container_param_list[i].replace('*', '_ptr').replace('&', '_link').replace(' ', '_')

    for i in range(len(container_param_list)):
        for template_struct_field in template_struct.field_list:
            if not isinstance(template_struct_field, Field):
                continue

            old_template_struct_field_type = template_struct_field.type + template_struct_field.type_suffix
            clear_template_struct_field_type = template_struct_field.type.replace('*', '').replace('&', '')
            if template_struct.template_param_list[i] == clear_template_struct_field_type: # T == T
                template_struct_field.type = template_struct_field.type.replace(template_struct.template_param_list[i], container_param_list[i], 1)
                if old_template_struct_field_type != template_struct_field.type:
                    pass
                    # print(f'change field type in {clean_struct_name}: {old_template_struct_field_type} -> {template_struct_field.type}')

            if template_struct.name in template_struct_field.type:
                template_struct_field.type = template_struct_field.type.replace(template_struct.name, clean_struct_name)
                if old_template_struct_field_type != template_struct_field.type:
                    pass
                    # print(f'change field type in {clean_struct_name}: {old_template_struct_field_type} -> {template_struct_field.type}')

            # stack[SIZE] -> stack[8]
            if len(template_struct_field.name_suffix):
                old_template_struct_field_name_suffix = template_struct_field.name_suffix
                template_struct_field.name_suffix = template_struct_field.name_suffix.replace(template_struct.template_param_list[i], container_param_list[i], 1)
                if old_template_struct_field_name_suffix != template_struct_field.name_suffix:
                    pass
                    # print(f'change field name_suffix in {clean_struct_name}: {old_template_struct_field_name_suffix} -> {template_struct_field.name_suffix}')

    template_struct.name = clean_struct_name

    if is_ret_gen:
        return template_struct

    if struct_name not in generated_struct_dict:
        generated_struct_dict[struct_name] = {}

    generated_struct_dict[struct_name][template_struct.name] = template_struct

    # print(f'{clean_struct_name=}')

    changed_field = copy.deepcopy(fld)
    changed_field.type = clean_struct_name

    return changed_field


def parse_struct_field_for_template(fld):
    if len(fld.type_template) <= 0:
        # no template field
        return None, None, None
    # elif len(fld.type_template) > 1:
    #     print(f'WARNING!!! WRONG TEMPLATE FIELD {fld.type}')
    #     return None, None, None

    template_struct_name = fld.type

    container_param_list = []
    for field_template in fld.type_template:
        field_template_full = field_template.type + field_template.type_suffix
        container_param_list.append(field_template_full)

    suffix = fld.type_suffix

    # print(f'parsed field "{fld.type}{fld.type_suffix}" -> {template_struct_name}, {container_param_list}, {suffix}')

    return template_struct_name, container_param_list, suffix


def check_template_fields():
    for key, struct in struct_dict.items():
        if not isinstance(struct, Struct):
            continue

        for i, fld in enumerate(struct.field_list):
            if not isinstance(fld, Field):
                continue

            template_struct_name, container_param_list, suffix = parse_struct_field_for_template(fld)
            if not template_struct_name:
                continue

            # if 'zCBolt' in struct.name:
            #     pass
            #     container_param_list = [p.replace('zCBolt', struct.name) for p in container_param_list]

            if template_struct_name not in template_struct_dict:
                continue

            changed_field = create_dynamic_struct(struct.name, copy.deepcopy(template_struct_dict[template_struct_name]), fld, container_param_list, suffix)
            if changed_field:
                struct.field_list[i] = changed_field


def add_defines():
    return'''
#define THREAD_PRIORITY_TIME_CRITICAL  15
#define THREAD_PRIORITY_HIGHEST         2
#define THREAD_PRIORITY_ABOVE_NORMAL    1
#define THREAD_PRIORITY_NORMAL          0
#define THREAD_PRIORITY_BELOW_NORMAL   -1
#define THREAD_PRIORITY_LOWEST         -2
#define THREAD_PRIORITY_IDLE          -15

#define D3DVALUE float
#define D3DCOLOR unsigned int

typedef struct _GUID {
    unsigned int   Data1;
    unsigned short Data2;
    unsigned short Data3;
    unsigned char  Data4[8];
} GUID;

typedef float (*LerpFunc) (const float, const float);
typedef int (*Compare) (const void*, const void*);
typedef int (*SearchFunc) (const zSEvasionSearchDesc&);
typedef void (*OnExit) ();
typedef void(*MsgFunc) (zSTRING);

typedef int(*EvalFuncPtr) (const zSTRING& s, zSTRING& msg);
typedef void(*ChangedFunc) (const zSTRING& s);
'''


def build_c_header(output_file_path, is_add_defines=True):

    global_enum_item_set = set()
    global_variables_set = set()
    global_enum_item_name_dict = dict()

    def build_enum(enum_obj, depth):
        if 'VolatileOverflowMode' in enum_obj.name or 'VolatileOverflowMode' in enum_obj.typedef_name:
            pass

        if not len(enum_obj.item_list):
            return ''

        typedef = ''
        if enum_obj.is_typedef:
            typedef = 'typedef '

        prefix = typedef + 'enum'

        if enum_obj.is_class:
            prefix += ' class'

        if enum_obj.name != 'anonymous':
            prefix += ' ' + enum_obj.name

            if enum_obj.base_type:
                prefix += ' : ' + enum_obj.base_type

        enum_text = ''
        enum_text += ('\t' * depth) + prefix + ' {\n'

        for idx, item in enumerate(enum_obj.item_list):
            # line = item.name
            # if item.name in global_enum_item_set or item.name in global_variables_set:
            name = item.name
            if enum_obj.name != ANON_NANE:
                name = f'{enum_obj.name}_{item.name}'

            line = f'{name}'
            global_enum_item_name_dict[item.name] = f'{name}'
            global_enum_item_set.add(item.name)

            if item.value:
                value = item.value
                value_splited = item.value.split()
                for part in value_splited:
                    if part in global_enum_item_name_dict:
                        value = value.replace(part, f'{global_enum_item_name_dict[part]}')

                line += f' = {value}'

            # Не оставляем запятую после последнего элемента.
            if idx != len(enum_obj.item_list) - 1:
                line += ','

            enum_text += ('\t' * (depth + 1)) + line + '\n'

        typedef_name = ''
        if enum_obj.is_typedef and len(enum_obj.typedef_name):
            typedef_name = ' ' + enum_obj.typedef_name
        enum_text += ('\t' * depth) + '}' + typedef_name + ';\n'

        return enum_text

    def build_field(fld):
        def build_filed_template(filed_template):
            filed_template_line = ''
            # filed_template_line += f'<{filed_template[0]}>'
            return filed_template_line

        field_line = ''
        field_line +=  f'{fld.type}'
        if len(fld.type_template):
            field_line += f'{build_filed_template(fld.type_template)}'
        field_line += f'{fld.type_suffix}'
        field_line += f' {fld.name}'

        name_suffix = f'{fld.name_suffix}'
        name_suffix_clear = name_suffix.replace('[', ' ').replace(']', ' ')
        name_suffix_clear_splited = name_suffix_clear.split()
        for part in name_suffix_clear_splited:
            if part in global_enum_item_name_dict:
                name_suffix = name_suffix.replace(part, f'{global_enum_item_name_dict[part]}')

        field_line += f'{name_suffix}'


        if len(fld.value_kind) and len(fld.value):
            field_line += f'\t\t{fld.value_kind} {fld.value}'
        field_line += f';'

        return field_line

    def build_struct(strct, depth, is_commented=False, source=''):
        if not len(strct.field_list) and strct.name == ANON_NANE:
            return ''

        # print(f'build struct {strct.name}')

        comm = '// ' if is_commented else ''
        strct_name = '' if strct.name == ANON_NANE else strct.name + ' '
        struct_text = ''

        struct_text += ('\t' * depth) + f'// size: 0x{strct.size:X}\n'

        if len(source):
            pass
        elif len(strct.header):
            struct_text += ('\t' * depth) + f'// source: {strct.header}.h\n'

        if len(strct.parent_list):
            struct_text += ('\t' * depth) + f'// parents: '
            for i, par in enumerate(strct.parent_list):
                if i != 0:
                    struct_text += f', '
                struct_text += f'{par}'
            struct_text += '\n'

        if len(strct.dependency_set):
            struct_text += ('\t' * depth) + f'// dependency: '
            for i, dep in enumerate(strct.dependency_set):
                if i != 0:
                    struct_text += f', '
                struct_text += f'{dep}'
            struct_text += '\n'

        if strct.pack:
            struct_text += comm + strct.pack + '\n'

        struct_text += comm + ('\t' * depth) + f'{strct.type} ' + strct_name + '{\n'

        for fld in strct.field_list:
            if isinstance(fld, PreprocessorDirective):
                struct_text += comm + f'{fld.text}\n'

            elif isinstance(fld, Field):
                builded_field = build_field(fld)
                builded_field_prepared = builded_field.replace(' ', '').replace('\t', '')
                original_field_prepared = fld.original_text.replace(' ', '').replace('\t', '')
                if original_field_prepared != builded_field_prepared and len(original_field_prepared):
                    struct_text += comm + ('\t' * depth) + f' // {fld.original_text}\n'
                struct_text += comm + ('\t' * depth) + f'\t{builded_field}\n'

            elif isinstance(fld, Struct):
                struct_txt = build_struct(fld, depth + 1, is_commented=is_commented)
                if len(struct_txt):
                    struct_text += struct_txt

            elif isinstance(fld, Enum):
                enum_txt = build_enum(fld, depth + 1)
                if len(enum_txt):
                    struct_text += enum_txt

        struct_text += comm + ('\t' * depth) + '};\n'

        if strct.pack:
            struct_text += comm + '#pragma pack( pop )' + '\n'

        for dep in strct.dependency_set:
            if dep not in struct_text:
                print(f'WARNING!!! {dep=} not in struct {struct_text}')

        return struct_text

    c_header = ''

    if len(struct_dict):
        c_header += '// === Forward Declarations ===\n'
        for struct in struct_dict.values():
            if not isinstance(struct, Struct):
                continue
            c_header += f'struct {struct.name};\n'

    if is_add_defines:
        c_header += '// === Custom Defines ===\n'
        defines = add_defines()
        c_header += defines + '\n'

    if len(global_field_list):
        c_header += '// === Global Variables ===\n'
        for fld in global_field_list:
            if fld.name in global_variables_set:
                continue
            builded_fld = build_field(fld)
            c_header += f'{builded_fld}\n'
            global_variables_set.add(fld.name)

    c_header += '\n'
    c_header += '\n'

    if len(enum_dict):
        # for enum_name, enum_obj in enum_dict.items():
        #     if enum_obj.name == 'anonymous':
        #         continue
        #
        #     if enum_obj.is_class:
        #         if enum_obj.base_type:
        #             c_header += f'enum class {enum_name} : {enum_obj.base_type};\n'
        #         else:
        #             c_header += f'enum class {enum_name};\n'
        #     else:
        #         if enum_obj.base_type:
        #             c_header += f'enum {enum_name} : {enum_obj.base_type};\n'
        #         else:
        #             c_header += f'enum {enum_name};\n'

        c_header += '\n'
        c_header += '\n'

        # Сначала выводим top-level enum, затем struct.
        # Так если struct использует enum как тип поля, enum уже определён.
        for enum_obj in enum_dict.values():
            enum_text = build_enum(enum_obj, 0)
            if len(enum_text):
                c_header += enum_text + '\n'

    # header_name = ''
    # already_used_generated_struct_header_dict = dict()
    # for obj in struct_dict.values():
    #     if isinstance(obj, Struct):
    #         if obj.name in generated_struct_dict:
    #             for generated_struct in generated_struct_dict[obj.name].values():
    #                 is_already_used = generated_struct.name in already_used_generated_struct_header_dict
    #                 already_used_name = already_used_generated_struct_header_dict.get(generated_struct.name, '')
    #                 struct_text = build_struct(generated_struct, 0, is_already_used)
    #                 if len(struct_text):
    #                     if is_already_used:
    #                         c_header += f'// === Is already announced in {already_used_name}.h ===\n'
    #                     else:
    #                         already_used_generated_struct_header_dict[generated_struct.name] = header_name
    #                     c_header += struct_text + '\n'
    #
    #         struct_text = build_struct(obj, 0)
    #         if len(struct_text):
    #             c_header += struct_text + '\n'
    #     elif isinstance(obj, Comment):
    #         header_name = obj.string
    #         c_header += f'\n// === {header_name}.h ===\n\n\n'

    already_used_generated_struct_header_dict = dict()
    for struct_name in struct_dependency_solved:
        if struct_name not in struct_dict:
            continue

        struct = struct_dict[struct_name]
        if not isinstance(struct, Struct):
            continue

        if struct.name in generated_struct_dict:
            for generated_struct in generated_struct_dict[struct.name].values():
                is_already_used = generated_struct.name in already_used_generated_struct_header_dict
                already_used_name = already_used_generated_struct_header_dict.get(generated_struct.name, '')
                struct_text = build_struct(generated_struct, 0, is_already_used, already_used_name)
                if len(struct_text):
                    if is_already_used:
                        c_header += f'// === Is already announced in {already_used_name} ===\n'
                    else:
                        already_used_generated_struct_header_dict[generated_struct.name] = struct.name
                    c_header += struct_text + '\n'

        struct_text = build_struct(struct, 0)
        if len(struct_text):
            c_header += struct_text + '\n'

    for extra_generated_struct_name, extra_generated_struct in extra_generated_struct_dict.items():
        struct_text = build_struct(extra_generated_struct, 0)
        if len(struct_text):
            c_header += struct_text + '\n'


    save_path = current_file_folder / Path(output_file_path)
    if save_path.exists():
        save_path.unlink()
    save_path.write_text(c_header)

    size_dict = dict()
    for strct in struct_dict.values():
        if isinstance(strct, Struct):
            size_dict[strct.name] = strct.size

    size_json = json.dumps(size_dict, ensure_ascii=False, indent=4)

    size_save_path = current_file_folder / 'types_size.json'
    if size_save_path.exists():
        size_save_path.unlink()
    size_save_path.write_text(size_json)


def parse_for_include(header_text):
    line_list = header_text.splitlines()
    if len(line_list) < 1:
        return []

    include_list = []
    for line in line_list:
        if '#include' not in line:
            continue

        if '.h' not in line:
            continue

        include_parts = line.split()
        header = include_parts[-1]
        header = header.replace('"', '').replace('<', '').replace('>', '').replace('.h', '').strip()
        include_list.append(header)

    return include_list


def topological_order_ignore_cycles(dependency_dict):
    """
    dependency_dict:
        ключ — имя файла;
        значение — список имен файлов, от которых он зависит.

    Возвращает список файлов.
    Циклические зависимости не вызывают ошибку.
    """

    files = []
    seen = set()

    def add(name):
        if name not in seen:
            seen.add(name)
            files.append(name)

    # Все файлы из ключей
    for name in dependency_dict:
        add(name)

    # Все файлы из зависимостей
    for deps in dependency_dict.values():
        if deps:
            for dep in deps:
                add(dep)

    if not files:
        return []

    visited = set()
    in_progress = set()
    result = []

    def dfs(name):
        if name in visited:
            return

        in_progress.add(name)

        deps = dependency_dict.get(name, []) or []

        # dict.fromkeys() убирает дубликаты
        for dep in dict.fromkeys(deps):
            # Пропускаем самозависимости и циклы
            if dep == name or dep in in_progress:
                continue

            dfs(dep)

        in_progress.discard(name)
        visited.add(name)
        result.append(name)

    for name in files:
        dfs(name)

    return result


def resolve_dependencies():
    global ordered_header_list

    for header_path in HEADER_FOLDER_PATH.rglob('*.h'):
        header_text = header_path.read_text()
        include_list = parse_for_include(header_text)
        file_name = header_path.stem

        header_dependency_dict[file_name] = include_list
        # print(f'{file_name} -> {include_list}')

    if 'z3d' in header_dependency_dict:
        header_dependency_dict['z3d'].append('zAlgebra')

    if 'zRenderer' in header_dependency_dict:
        header_dependency_dict['zRenderer'].append('zAlgebra')
        header_dependency_dict['zRenderer'].append('zString')
        header_dependency_dict['zRenderer'].append('zTypes3d') # ???

    if 'zResource' in header_dependency_dict:
        header_dependency_dict['zResource'].append('zObject')

    ordered_header_list = topological_order_ignore_cycles(header_dependency_dict)


def fix_broken_class_and_fields():
    def fix_struct_fields(struct, struct_fix_data_list):
        for i, fld in enumerate(struct.field_list):
            if not isinstance(fld, Field):
                continue

            for field_name_old, field_name_new, field_size in struct_fix_data_list:
                if fld.name != field_name_old:
                    continue

                field_name = field_name_new if len(field_name_new) else field_name_old

                fixed_field = Field(type='char', name=field_name, name_suffix=f'[{field_size}]', original_text=fld.original_text)
                struct.field_list[i] = fixed_field


    char_fill_dict = {
        'zCPolygon':      [['flags', 'TFlags_flags', '0x03'], ], # c99 bn bug...

        'zCRayTurboAdmin':      [['m_mapRayTurbos', '', '0x0C'], ],
        'zCVobLight':           [['affectedPolyMap', '', '0x0C'], ],
        'zCNetMessageQueue':    [['queue', 'zQUEUE_zCNetMessage', '0x0C'], ],
        'zCArchiverGeneric':    [['writeObjectList', 'zCSparseArray_zCObject_ptr_zTWriteObjectEntry_writeObjectList', '0x20'], ],
        'zCWorld':              [['zoneBoxSorter', 'zCVobBBox3DSorter_zCZone_zoneBoxSorter', '0x44'],
                                ['zoneActiveHandle', 'zCVobBBox3DSorter_zCZone_zTBoxSortHandle_zoneActiveHandle', '0x44'], ],
        'zCDrvProperties_MSS':  [
            # ['use3dProvider', '', '0x14'],
            # ['provNames', '', '0x190'],
            ['waveFormat', '', '0x10'],
            # ['providers', '', '0x50']
        ],
    }

    struct_size_dict = {'zVEC2': 0x08, 'zVEC3': 0x0C, 'zVEC4': 0x10, 'zMAT3': 0x24, 'zMAT4': 0x40, 'zCQuat': 0x10,
                        'zTPlane': 0x10, 'zSTRING': 0x14, 'zGOTHIC_FILE': 0x20, 'zFINDDATA': 0x128, 'zCOLOR': 0x04,
                        'zTNetPacket': 0x1C, 'zComplex': 0x10, 'zCValueSmooth': 0x10, 'zCVEC3Smooth': 0x20,
                        'zCSparseArrayManDat': 0x04, 'zCSparseArrayIterator': 0x0C, 'zCSparseArrayBase': 0x20,
                        'zCLine2D': 0x10, 'zCCacheBase': 0x10, 'zCAccount': 0x01, 'oCText': 0x01,

                        'zCWorldPerFrameCallback': 0x08, # parent empty 0x1 -> 0x4 + vtable
                        'zCVobCallback': 0x08, # parent empty 0x1 -> 0x4 + vtable
                        'zCCollObjectCharacter': 0x016C, # in header wrong size
                        'oCCollObjectCharacter': 0x0174, # in header wrong size
                        }

    for strct in struct_dict.values():
        if not isinstance(strct, Struct):
            continue

        if strct.name in struct_size_dict:
            strct.size = struct_size_dict[strct.name]

        for struct_name, strct_fix_data_list in char_fill_dict.items():
            if strct.name != struct_name:
                continue

            fix_struct_fields(strct, strct_fix_data_list)

    struct_to_delete_list = ['anonymous', 'zSNode', 'zTBoxSortHandle', 'zCVobBBox3DSorter', 'zCBBox3DSorterBase',
                             'zCBBox3DSorterBase_zTBoxSortHandle', 'zCBBox3DSorterBase_zTNode']
    for struct_to_delete in struct_to_delete_list:
        struct_dict.pop(struct_to_delete, None)

    for strct in struct_dict.values():
        if not isinstance(strct, Struct):
            continue

        if strct.name == 'zCArraySort':
            strct.field_list.append(Field(type='Compare', name='compare_func')) # last

        if strct.name == 'zCListSort':
            strct.field_list.insert(0, Field(type='Compare', name='compare_func')) # first

        if strct.name == 'zList':
            strct.field_list.insert(0, Field(type='Compare', name='compare_func')) # first

        if strct.name == 'zSEvasionSearchDesc':
            strct.field_list.insert(0, Field(type='SearchFunc', name='search_func'))

        if strct.name == 'zERROR':
            strct.field_list.insert(0, Field(type='OnExit', name='on_exit'))

        # typedef void(*MsgFunc) (zSTRING);
        if strct.name == 'zCParser':
            strct.field_list.insert(0, Field(type='MsgFunc', name='msg_func'))

        # typedef int(*EvalFuncPtr) (const zSTRING& s, zSTRING& msg);
        # typedef void(*ChangedFunc) (const zSTRING& s);
        if strct.name == 'zCConsole':
            strct.field_list.insert(17, Field(type='ChangedFunc', name='changed_func'))
            strct.field_list.insert(17, Field(type='EvalFuncPtr', name='eval_func_ptr', name_suffix='[zCON_MAX_EVAL]'))

        # zCCollisionObject* (*m_createNewInstance)(void);
        if strct.name == 'zCCollisionObjectDef':
            strct.field_list.insert(0, Field(type='zCCollisionObject', type_suffix='*', name='(*m_createNewInstance)(void)'))

        if strct.name == 'zCClassDef':
            strct.field_list.insert(4, Field(type='zCObject', type_suffix='*', name='(*createNewInstanceBackup)(void)'))
            strct.field_list.insert(4, Field(type='zCObject', type_suffix='*', name='(*createNewInstance)(void)'))

        # zCArray<int(* * )( const zSEvasionSearchDesc& )> searchFuncs;
        if strct.name == 'zCPathSearch':
            strct.field_list.append(Field(type='char', name='zCArray_zSEvasionSearchDesc_searchFuncs',
                                          name_suffix=f'[0x0C]',
                                          original_text='zCArray<int(* * )( const zSEvasionSearchDesc& )> searchFuncs'))

        # zCArray<int(*)( zCOptionEntry& )> ccbList;
        if strct.name == 'zCOptionEntry':
            strct.field_list.insert(1, Field(type='char', name='zCArray_int_zCOptionEntry_ccbList',
                                          name_suffix=f'[0x0C]',
                                          original_text='zCArray<int(*)( zCOptionEntry& )> ccbList'))

        if strct.name == 'zCOption':
            strct.field_list.insert(2, Field(type='zFILE', type_suffix='*', name='directory',
                                          name_suffix=f'[0x1A]',
                                          original_text='zCArray<zCOptionSection*> sectionList;'))

        # zCDrvProperties_MSS // sizeof 220h
        if strct.name == 'zCDrvProperties_MSS':
            strct.pack = '#pragma pack( push, 1 )'

        # if strct.name == 'zCLightning':
        #     strct.field_list[0].type = 'zCLightning_zCBolt'

        # if strct.name == 'zCFlash':
        #     strct.field_list[3].type = 'zCFlash_zCBolt'
        #     strct.field_list[4].type = 'zCFlash_zCBolt'



        # zCPatchMap что то непонятное с размером, пока оставим так


        for fld_ in strct.field_list:
            if not isinstance(fld_, Field):
                continue

            if fld_.type == 'oCNpc::oSDamageDescriptor':
                fld_.type = 'oSDamageDescriptor'

            if fld_.type == 'zCSurfaceCache_D3D::zCSlotIndex':
                fld_.type = 'zCSlotIndex'

            if fld_.type == 'IDirect3DVertexBuffer7' and fld_.type_suffix == '*':
                fld_.type = 'void'

            if fld_.type not in struct_dict:
                if f'{strct.name}_{fld_.type}' in struct_dict:
                    fld_.type = f'{strct.name}_{fld_.type}'

            # if 'zCBolt' in strct.name:

            # if 'zCSoundManager' == strct.name:
            field_original_text = fld_.original_text
            for type_template in fld_.type_template:
                if type_template.type not in struct_dict:
                    struct_name_splited = strct.name.split('_')
                    computed_name = f'{strct.name}_{type_template.type}'
                    if len(struct_name_splited) == 2 and struct_name_splited[-1] == type_template.type:
                        type_template.type = strct.name
                    elif computed_name in struct_dict:
                        type_template.type = computed_name
                        pass

                            # if 'zCVobBBox3DSorter' in fld.type:
            #     print(fld)

            # if fld.type == 'zCVobBBox3DSorter<zCZone>':
            #     fld.type = 'char zCVobBBox3DSorter_zCZone[0x44]'
            #
            # if fld.type == 'zCVobBBox3DSorter<zCZone> : : zTBoxSortHandle':
            #     fld.type = 'char zCVobBBox3DSorter_zCZone_zTBoxSortHandle[0x44]'
            #
            # if fld.type == 'zCBBox3DSorterBase*':
            #     fld.type = 'char zCBBox3DSorterBase_ptr[0x04]'


def swap_struct_positions():
    global struct_dict

    struct_name_list = [['zCClassDef', 'zCObject'], ['zCResource', 'zCClassCache']]
    new_struct_dict = {}
    for key1, key2 in struct_name_list:
        for k, v in struct_dict.items():
            if k == key1:
                new_struct_dict[key2] = struct_dict[key2]
            elif k == key2:
                new_struct_dict[key1] = struct_dict[key1]
            else:
                new_struct_dict[k] = v

    struct_dict = new_struct_dict


def resolve_struct_dependency():
    global struct_dependency_solved

    def get_struct_dependency(strct):
        dependency_set = set()
        for fld in strct.field_list:
            if isinstance(fld, Field):
                field_type = fld.type

                # zCCSProps::zTCSRunBehaviour runBehaviour; -> zCCSProps
                if '::' in field_type:
                    field_type = field_type.split('::')[0].split('<')[0].strip()

                if field_type in struct_dict:
                    if field_type in struct_dict or field_type in generated_struct_dict:
                        if '*' not in fld.type_suffix:
                            dependency_set.add(field_type)

                for field_template in fld.type_template:
                    if not isinstance(field_template, FieldTemplate):
                        continue

                    if field_template.type in struct_dict or field_template.type in generated_struct_dict:
                        if '*' not in fld.type_suffix:
                            dependency_set.add(field_template.type)

            elif isinstance(fld, Struct):
                dependency_set.update(get_struct_dependency(fld))

        return dependency_set

    struct_dependency = dict()
    for struct in struct_dict.values():
        if not isinstance(struct, Struct):
            continue

        struct_dependency[struct.name] = get_struct_dependency(struct)

        if struct.name in struct_dependency and len(struct_dependency[struct.name]):
            struct.dependency_set = struct_dependency[struct.name]

    struct_dependency_solved = topological_order_ignore_cycles(struct_dependency)

    # print(f'{struct_dependency_solved=}')


def start_tests():
    global struct_dict, template_struct_dict, generated_struct_dict, enum_dict
    global header_struct_dict, struct_dependency_solved

    tests_folder_path = HEADER_FOLDER_PATH.parent.parent / 'tests'
    for header in tests_folder_path.rglob('*.h'):
        file_name = header.stem
        if '_result' in file_name:
            continue

        if '1' in file_name:
            continue

        if '2' in file_name:
            continue

        if '3' in file_name:
            continue

        if '4' in file_name:
            continue

        # if '5' in file_name:
        #     continue

        struct_dict = dict()
        header_struct_dict = dict()
        template_struct_dict = dict()
        generated_struct_dict = dict()
        enum_dict = dict()
        struct_dependency_solved = []

        # add_missing()
        parse_header(header)
        set_personal_inheritance()
        set_vtable()
        extract_template_struct()
        check_template_fields()
        resolve_struct_dependency()


        output_file_path = tests_folder_path / (file_name + '_result.h')
        build_c_header(output_file_path, is_add_defines=False)


if False: # True, False
    start_tests()
else:
    resolve_dependencies()
    add_missing()
    start_parse()

    fix_broken_class_and_fields() # <- before vtab
    # add_inheritance_and_vtable() # <- after fix
    set_personal_inheritance() # <- after fix
    set_vtable()
    extract_template_struct()
    check_template_fields()
    resolve_struct_dependency()
    create_all_template_variables()
    build_c_header('c_header.h')


    #   // sizeof 50h
    #   class zCCSPoolItem : public zSTRING, public zCObject {


    # resolve_dependencies()
    # start_parse()
    # fix_broken_class_and_fields()
    # # add_vtable()
    # add_default_class_forward_declaration()
    # extract_template_struct()
    # check_template_fields()
    # # swap_struct_positions()
    # resolve_struct_dependency()
    # build_c_header('c_header.h')

# print(ordered_header_list)


print('END SCRIPT')
