from pathlib import Path
from typing import Any, List
from dataclasses import dataclass, field


@dataclass
class Unparsed:
    line: int = -1
    original_text: str = ''

@dataclass
class Function:
    line: int = -1
    original_text: str = ''
    address: int = -1
    return_type: str = ''
    call_conv: str = ''
    name: str = ''
    argument_list: List[str] = field(default_factory=list)
    is_static: bool = field(default=False)

@dataclass
class Variable:
    line: int = -1
    original_text: str = ''
    address: int = -1
    typ: str = ''
    name: str = ''


signature_list = list()
custom_type_cache = dict()

function_dict = {}

current_file_path = Path(__file__).resolve()
current_file_folder = current_file_path.parent
names_path = current_file_folder / 'headers' / 'Names.txt'


def parse_arg(argument):
    # zCMatrixStack<zMAT4, 8> trafoViewStack;            // sizeof 204h   offset 208h
    argument = argument.replace('class ', '').strip()
    argument = argument.replace('struct ', '').strip()
    argument = argument.replace('enum ', '').strip()
    argument = argument.replace(' *', '*').strip()
    argument = argument.replace(' &', '&').strip()

    if argument.count('<') > 1:
        return argument

    open_arrow_index = argument.find('<')
    close_arrow_index = argument.find('>')
    if open_arrow_index >= 0 and close_arrow_index >= 0 and open_arrow_index < close_arrow_index:
        template = argument[open_arrow_index + 1:close_arrow_index]
        template = template.replace('*', '_ptr')
        template = template.replace('&', '_link')
        template = template.replace(' ', '')
        template = template.replace(',', '_')
        result = argument[:open_arrow_index] + '_' + template + argument[close_arrow_index + 1:]

        return result

    return argument


def get_func_name_from_signature(signature_string, conv_call):
    open_bracket_index = signature_string.find('(')
    if open_bracket_index == -1:
        return ''

    conv_call_index = signature_string.find(conv_call)
    if conv_call_index == -1:
        return ''

    if conv_call_index + len(conv_call) >= open_bracket_index:
        return ''

    func_name = signature_string[conv_call_index + len(conv_call) + 1:open_bracket_index]
    func_name = func_name.replace('class', '')
    func_name = func_name.replace('struct', '')
    func_name = func_name.replace('enum', '')
    func_name = func_name.replace('  ', '')

    less_op_count = func_name.count('<')
    bigg_op_count = func_name.count('>')
    if less_op_count == bigg_op_count:
        func_name = func_name.replace('<', '_')
        func_name = func_name.replace('>', '_')
    func_name = func_name.replace(',', '_')
    func_name = func_name.replace('\'', '_')
    func_name = func_name.replace('`', '_')
    func_name = func_name.replace(' ', '_')
    func_name = func_name.replace('{', '_')
    func_name = func_name.replace('}', '_')
    func_name = func_name.replace('*', '_ptr')

    func_name = func_name.replace('_::', '::')
    func_name = func_name.strip('_')


    func_name = func_name.replace('__', '_')
    func_name = func_name.replace('__', '_')
    func_name = func_name.replace('__', '_')

    # print(f'func_name = {func_name}')

    # for char in func_name:
    #     if char in invalid_char:
    #         return ''
    #
    #     if char not in valid_char:
    #         return ''

    return func_name


def get_func_arguments_from_signature(signature_string):
    open_bracket_count = signature_string.count('(')
    if open_bracket_count > 1:
        return []

    close_bracket_count = signature_string.count(')')
    if close_bracket_count > 1:
        return []

    open_bracket_index = signature_string.find('(')
    close_bracket_index = signature_string.find(')')
    if close_bracket_index <= open_bracket_index:
        return []

    argument_string = signature_string[open_bracket_index + 1:close_bracket_index]
    if len(argument_string) < 2:
        return []

    argument_list = argument_string.split(',')

    argument_list_parsed = []
    for argument in argument_list:
        parsed_argument = parse_arg(argument)
        # print(f'change argument: {argument} -> {parsed_argument}')
        argument_list_parsed.append(parsed_argument)

    if len(argument_list_parsed) == 1 and argument_list_parsed[0] == 'void':
        argument_list_parsed = []

    return argument_list_parsed


def get_func_conv_call(signature_string):
    if '__thiscall' in signature_string:
        return '__thiscall'
    elif '__fastcall' in signature_string:
        return '__fastcall'
    elif '__cdecl' in signature_string:
        return '__cdecl'
    elif '__stdcall' in signature_string:
        return '__stdcall'
    else:
        return ''


def get_func_return_type(signature_string, conv_call):
    if conv_call not in signature_string:
        return ''

    # if ':' in signature_string:
    #     print('WARNING!!! Cant parse return type from :' + signature_string)

    signature_string = signature_string.split(conv_call)[0].strip()

    signature_string = signature_string.replace('public:', '').strip()
    signature_string = signature_string.replace('private:', '').strip()
    signature_string = signature_string.replace('protected:', '').strip()
    # signature_string = signature_string.split(':')[-1].strip()

    signature_string = signature_string.replace('virtual', '').strip()
    signature_string = signature_string.replace('static', '').strip()
    signature_string = parse_arg(signature_string).strip()

    if '`' in signature_string:
        return ''

    return signature_string


def parse_function_signature(line_index, original_text, address, signature_string, is_static):
    # 0x005DC470 public: __thiscall zCResource::zCResource(void)
    # print(signature_string)

    conv_call = get_func_conv_call(signature_string)
    conv_call_index = signature_string.find(conv_call)
    open_parentheses_index = signature_string.find('(')

    return_type = signature_string[:conv_call_index].strip()
    if len(return_type) <= 1:
        return_type = 'void'

    name = signature_string[conv_call_index + len(conv_call):open_parentheses_index].strip()
    arguments = get_func_arguments_from_signature(signature_string)

    signature_list.append(Function(line=line_index + 1, original_text=original_text, address=address,
                                   return_type=return_type, name=name, argument_list=arguments, is_static=is_static))
    # print(f'[{return_type}] [{name}] {arguments}')


def parse_variable_function_signature(line_index, original_text, address, signature_string):
    typ = ''
    name = ''
    if '__pInconsistency' in signature_string:
        typ = 'void (__cdecl*)()'
        name = '__pInconsistency'
    elif 'connectCallback' in signature_string:
        typ = 'int (__cdecl*)(void*)'
        name = 'connectCallback'
    elif 'zCExceptionHandler::m_previousFilter' in signature_string:
        typ = 'long (__stdcall*)(void*)'
        name = 'zCExceptionHandler::m_previousFilter'
    elif 'zCMenu::EnterCallback' in signature_string:
        typ = 'void (__cdecl*)()'
        name = 'zCMenu::EnterCallback'
    elif 'zCMenu::LeaveCallback' in signature_string:
        typ = 'void (__cdecl*)()'
        name = 'zCMenu::LeaveCallback'
    elif 'zCMenu::FrameCallback' in signature_string:
        typ = 'void (__cdecl*)()'
        name = 'zCMenu::FrameCallback'
    elif 'vidBlitFunc' in signature_string:
        typ = 'int (__fastcall**)(void*)'
        name = 'vidBlitFunc'
    elif 'winSetVideoMode' in signature_string:
        typ = 'int (__cdecl*)(void*)'
        name = 'winSetVideoMode'
    elif 'vidModeFilter' in signature_string:
        typ = 'int (__cdecl*)(void*)'
        name = 'vidModeFilter'

    if typ and name:
        signature_list.append(Variable(line=line_index + 1, original_text=original_text, address=address,
                                       typ=typ, name=name))
    else:
        signature_list.append(Unparsed(line=line_index + 1, original_text=original_text))


def split_string_pairs(text: str, separator: str = ' '):
    # список списков, каждый внутренний список из 2 элементов
    not_splt = [['signed', 'short'], ['signed', 'long'], ['signed', 'int'], ['signed', 'char']]

    if not separator:
        return [text]

    parts = text.split(separator)
    result = []

    for part in parts:
        if result and any(
            a and b and result[-1].endswith(a) and part.startswith(b)
            for a, b in not_splt
        ):
            result[-1] += separator + part
        else:
            result.append(part)

    return result


def replace_spaces_in_signature(signature_string: str) -> str:
    if not isinstance(signature_string, str):
        return signature_string

    parts = []
    start = 0

    while True:
        open_index = signature_string.find("`", start)

        if open_index == -1:
            parts.append(signature_string[start:])
            break

        close_index = signature_string.find("'", open_index + 1)

        if close_index == -1:
            parts.append(signature_string[start:])
            break

        # всё до `
        parts.append(signature_string[start:open_index])

        # сам `
        parts.append(signature_string[open_index])

        # содержимое между ` и '
        parts.append(signature_string[open_index + 1:close_index].replace(' ', '_'))

        # сам '
        parts.append(signature_string[close_index])

        start = close_index + 1

    return ''.join(parts)


def parse_variable_signature(line_index, original_text, address, signature_string):
    if 'vftable' in signature_string:
        signature_list.append(Variable(line=line_index + 1, original_text=original_text, address=address,
                                       name=signature_string))
        # print(f'[vt] {signature_string}')
        return

    signature_string = replace_spaces_in_signature(signature_string)

    if 'zCModelAni::classDef' in signature_string:
        pass

    typ = ''
    name = ''
    signature_string_splited = split_string_pairs(signature_string, ' ')
    if len(signature_string_splited) == 1:
        # can be same addr
        # __real@47c34f80
        # __real@406fe00000000000
        if '__real@' in signature_string:
            hex_part = name.split('@')[-1]
            if len(hex_part) <= 8:
                type_str = 'float'
            elif len(hex_part) <= 16:
                type_str = 'double'
            else:
                type_str = ''
            signature_list.append(Variable(line=line_index + 1, original_text=original_text, address=address,
                                           typ=type_str))
        else:
            name = signature_string_splited[0]
            signature_list.append(Variable(line=line_index + 1, original_text=original_text, address=address,
                                           name=name))
        # print(f'[1] {signature_string}')
    elif len(signature_string_splited) == 2:
        typ = '' if '?' in signature_string_splited[0] else signature_string_splited[0]
        typ = parse_arg(typ).strip()
        name = signature_string_splited[1]
        signature_list.append(Variable(line=line_index + 1, original_text=original_text, address=address,
                                       typ=typ, name=name))
        # print(f'[2] {signature_string}')
    elif len(signature_string_splited) == 3:
        # float (* m2)[33][33]
        if '(' in signature_string and '[' in signature_string and '*' in signature_string:
            name_start_index = signature_string.find('(')
            name_end_index = signature_string.find(')')
            typ = signature_string[:name_start_index + 2] + signature_string[name_end_index:]
            name = signature_string[name_start_index + 2:name_end_index].strip()
            signature_list.append(Variable(line=line_index + 1, original_text=original_text, address=address,
                                           typ=typ, name=name))
        # print(f'[3] {signature_string}')
    elif len(signature_string_splited) >= 4:
        # dont have this
        print(f'[{len(signature_string_splited)}] {signature_string}')
        pass


def parse_line(i, name_line, address_int, signature_string, is_static):
    # can be multiple
    conv_call = get_func_conv_call(signature_string)
    conv_call_index = signature_string.find(conv_call)
    open_parentheses_index = signature_string.find('(')
    close_parentheses_index = signature_string.find(')')

    if 'zCMenu::LeaveCallback' in signature_string:
        pass

    if len(conv_call):
        if signature_string[close_parentheses_index + 1:close_parentheses_index + 4] == "'::":
            # 0x0058DBE0 public: __thiscall `private: void __thiscall zCModelPrototype::ReadSoftSkinVertList(void)'::`2'::zTControlerWeight::zTControlerWeight(void)
            retutn_type = split_string_pairs(signature_string)[0].split('`')[0].strip()
            var_name = signature_string[close_parentheses_index + 1:]  # `::...
            signature_string = f'{retutn_type} {var_name}'
            parse_line(i, name_line, address_int, signature_string, is_static)
        else:
            if open_parentheses_index > conv_call_index:
                parse_function_signature(i, name_line, address_int, signature_string, is_static)
            else:
                parse_variable_function_signature(i, name_line, address_int, signature_string)
    else:
        parse_variable_signature(i, name_line, address_int, signature_string)


def parse_names():
    if not names_path.exists():
        return

    names_text = names_path.read_text()
    if len(names_text) < 32:
        return

    names_line_list = names_text.splitlines()
    if len(names_text) < 1:
        return

    for i, name_line in enumerate(names_line_list):
        if len(name_line) < 12:
            signature_list.append(Unparsed(line=i + 1, original_text=name_line))
            continue

        address_string = name_line[:10]
        address_int = 0
        try:
            address_int = int(address_string, 16)
        except:
            signature_list.append(Unparsed(line=i + 1, original_text=name_line))
            continue

        if address_int <= 0:
            signature_list.append(Unparsed(line=i + 1, original_text=name_line))
            continue

        if 'IMAGE_' in name_line:
            signature_list.append(Unparsed(line=i + 1, original_text=name_line))
            continue

        if 'oCNpc' in name_line and 'RTTI Type Descriptor' in name_line and 'oCShrinkHelper' in name_line:
            pass

        signature_string = name_line[10 + 1:]

        is_static = 'static' in signature_string

        signature_string = signature_string.replace('const', '').replace('  ', ' ').strip()
        signature_string = signature_string.replace('[thunk]:', '').replace('  ', ' ').strip()
        signature_string = signature_string.replace('class ', '').replace('  ', ' ').strip()
        signature_string = signature_string.replace('struct ', '').replace('  ', ' ').strip()
        signature_string = signature_string.replace('enum ', '').replace('  ', ' ').strip()

        signature_string = signature_string.replace('public: ', '').strip()
        signature_string = signature_string.replace('private: ', '').strip()
        signature_string = signature_string.replace('protected: ', '').strip()

        signature_string = signature_string.replace('virtual ', '').strip()
        signature_string = signature_string.replace('static ', '').strip()

        signature_string = signature_string.replace('? ?', '?_?').strip()
        signature_string = signature_string.replace('? :', '?_:').strip()
        signature_string = signature_string.replace(': ?', ':_?').strip()

        signature_string = signature_string.replace('< <', '<<').strip()
        signature_string = signature_string.replace('> >', '>>').strip()
        signature_string = signature_string.replace(', ', ',').strip()
        signature_string = signature_string.replace(' *', '*').strip()
        signature_string = signature_string.replace(' `', '`').strip()


        parse_line(i, name_line, address_int, signature_string, is_static)
    #
    #     func_name = get_func_name_from_signature(signature_string, conv_call)
    #     if len(func_name) < 1:
    #         # print(f'WARNING: cant parse function name: {signature_string}')
    #         continue
    #
    #     args = get_func_arguments_from_signature(signature_string)
    #     if len(args) < 1:
    #         # print(f'WARNING: uncorrent function arguments: {signature_string}')
    #         continue
    #
    #     return_type = get_func_return_type(signature_string, conv_call)
    #     if len(return_type) < 1:
    #         # print(f'WARNING: uncorrent function return type: {signature_string}')
    #         pass
    #
    #     is_static = 'static' in signature_string
    #     # 0063E8D0: zCVobSound::ProcessZoneList ['class zCArraySort<class zCZone *> const &', 'class zCArraySort<class zCZone *> const &', 'class zCWorld *']
    #     # 0x0069EF30 public: int __thiscall oCAISound::GetSoundMaterial(class zCVob *,enum zCSoundManager::zTSndManMedium &)
    #     # print(f'{address_int:08X}: {func_name} {args}')
    #
    #     function_dict[address_int] = {'name': func_name, 'return_type': return_type, 'is_static': is_static,
    #                                   'calling_conventions': conv_call, 'arguments': args}
    #
    # _json = json.dumps(function_dict, ensure_ascii=False, indent=4)
    #
    # current_dir = Path(__file__).resolve().parent
    # save_path = current_dir / 'functions_signature.json'
    # if save_path.exists():
    #     save_path.unlink()
    # save_path.write_text(_json)

    # for signature in signature_list:
    #     print(signature)


def bn_get_type(type_string: str):
    bn_type = None
    if type_string in custom_type_cache:
        bn_type = custom_type_cache[type_string]
        # print(f'Get "{type_string}" from cache')
    else:
        argument_varialbe_list = [type_string, type_string.replace('::', '_'), type_string.split('::')[-1]]
        for argument_varialbe in argument_varialbe_list:
            try:
                bn_type, _ = bv.parse_type_string(argument_varialbe)
                # print(f'parsed type: {bn_type}')
                break
            except:
                bn_type = None

        if bn_type is None:
            if '*' in type_string or '&' in type_string:
                void_type = bn.Type.void()
                bn_type = bn.Type.pointer(bv.arch, void_type)

        custom_type_cache[type_string] = bn_type

    if bn_type is None:
        print(f'WARNING!!! Cant parse bn type: {type_string}')

    return bn_type


def bn_get_argument_list(function_name, argument_list, is_static):
    void_type = bn.Type.void()
    void_pointer_type = bn.Type.pointer(bv.arch, void_type)

    params = [void_pointer_type] * len(argument_list)
    for i, argument in enumerate(argument_list):
        parsed_type = bn_get_type(argument)
        if parsed_type is not None:
            params[i] = parsed_type

    if not is_static:
        function_name_splited = function_name.split('::')
        this = function_name_splited[0].strip()
        this_found = False
        if len(function_name_splited) == 2:
            parsed_type = bn_get_type(this + '*')
            if parsed_type:
                params.insert(0, parsed_type)
                this_found = True

        if not this_found:
            params.insert(0, void_pointer_type)

    return params


def bn_add_function(signature: Function):
    func = bv.get_function_at(signature.address)
    if not func:
        return

    # if 'ResourceManager' not in signature.name:
    #     return

    if len(signature.name):
        try:
            symbol = Symbol(SymbolType.FunctionSymbol, signature.address, signature.name)
            bv.define_user_symbol(symbol)
        except:
            pass

    return_type = func.type.return_value
    return_type_temp = bn_get_type(signature.return_type)
    if return_type_temp is not None:
        return_type = return_type_temp
        # print(f'changing return type {return_type_string} -> {return_type}')

    calling_conventions = func.calling_convention
    calling_conventions_string = signature.call_conv
    if calling_conventions_string:
        calling_conventions_string = calling_conventions_string.replace('__', '').strip()
        try:
            calling_conventions = func.arch.calling_conventions[calling_conventions_string]
        except:
            pass

    params = bn_get_argument_list(signature.name, signature.argument_list, signature.is_static)
    try:
        new_function_type = bn.Type.function(return_type, params, calling_convention=calling_conventions)
        func.type = new_function_type
    except:
        pass


def bn_add_var(signature: Variable):
    if signature.address <= 0:
        return

    if not bv.is_valid_offset(signature.address):
        return

    if len(signature.name):
        try:
            symbol = Symbol(SymbolType.DataSymbol, signature.address, signature.name)
            bv.define_user_symbol(symbol)
        except:
            pass

    if len(signature.typ):
        try:
            bn_type = bn_get_type(signature.typ)
            if bn_type is not None:
                bv.define_user_data_var(signature.address, bn_type)
        except:
            print(f'WARNING!!! Cant add variable to data: {signature.typ}')
            pass


def bn_add():
    global bn

    try:
        import binaryninja as bn
    except ImportError:
        return

    bv.begin_undo_actions()

    print('START SCRIPT')

    for s in signature_list:
        if isinstance(s, Function):
            bn_add_function(s)
            pass
        elif isinstance(s, Variable):
            bn_add_var(s)

    print('FINISH SCRIPT')

    bv.commit_undo_actions()

parse_names()
bn_add()
