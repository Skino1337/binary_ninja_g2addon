from binaryninja import HighLevelILOperation, TypeClass, Type, StructureType
import re
import traceback


def get_call_return_type(src):
    """
    Универсальное извлечение типа без хардкода.
    Парсит текстовую сигнатуру указателя на функцию, отдавая результат ядру.
    """
    right_type = None
    try:
        if hasattr(src, 'dest') and src.dest and hasattr(src.dest, 'expr_type'):
            call_dest_type = src.dest.expr_type
            if call_dest_type:
                type_str = str(call_dest_type).strip()
                print(f'{call_dest_type=}')

                # Если это сигнатура указателя на функцию (содержит (*)... или просто скобки)
                if "(" in type_str:
                    # Корректно отсекаем всё, начиная со скобки указателя функции
                    type_part = re.split(r'\s*\(\s*\*\s*\)', type_str)[0].strip()
                    # Если звездочки не было (прямой прототип), берем левую часть до первой скобки
                    type_part = type_part.split('(')[0].strip()

                    if type_part and type_part != "void":
                        try:
                            # Компилируем строку типа обратно в объект Type ядра Binary Ninja
                            parsed_res = bv.parse_type_string(type_part)
                            if isinstance(parsed_res, tuple) and parsed_res:
                                right_type = parsed_res[0]
                        except Exception:
                            pass

                # Резерв: если тип поля сам по себе содержит прямое свойство return_type
                if not right_type and hasattr(call_dest_type, 'return_type') and call_dest_type.return_type:
                    right_type = call_dest_type.return_type
    except Exception:
        pass

    # Финальный резерв самого декомпилятора, если все остальные способы провалились
    if not right_type and hasattr(src, 'expr_type') and src.expr_type:
        right_type = src.expr_type

    return right_type


def get_type_from_array_math(src):
    """
    Проверяет, является ли src операцией получения элемента по индексу.
    Возвращает УКАЗАТЕЛЬ на тип элемента массива, если размеры совпадают.
    """
    # Защита: проверяем, что корень операции действительно сложение (HLIL_ADD)
    if src.operation != HighLevelILOperation.HLIL_ADD:
        return None

    left_op = src.left
    right_op = src.right

    mul_op = None
    base_array_expr = None

    # 2. Ищем, какая из частей является умножением (*)
    if left_op.operation == HighLevelILOperation.HLIL_MUL:
        mul_op = left_op
        base_array_expr = right_op
    elif right_op.operation == HighLevelILOperation.HLIL_MUL:
        mul_op = right_op
        base_array_expr = left_op

    if not mul_op:
        return None

    # 3. Находим константу-множитель (шаг / размер структуры в байтах)
    stride = None

    if mul_op.left.operation == HighLevelILOperation.HLIL_CONST:
        stride = mul_op.left.constant
    elif mul_op.right.operation == HighLevelILOperation.HLIL_CONST:
        stride = mul_op.right.constant

    if stride is None:
        return None

    # Получаем архитектуру для создания указателя в будущем
    arch = src.function.arch
    bv = src.function.view

    # 4. ДИНАМИЧЕСКАЯ ПРОВЕРКА ТИПА
    base_type = base_array_expr.expr_type

    if base_type:
        element_type = None

        # Случай А: База — это УКАЗАТЕЛЬ на структуру (как в вашем случае с *parray)
        if base_type.type_class == TypeClass.PointerTypeClass:
            element_type = base_type.target

        # Случай Б: База — это СТАТИЧЕСКИЙ МАССИВ структур (например, parray[10])
        elif base_type.type_class == TypeClass.ArrayTypeClass:
            element_type = base_type.element_type

        # Если мы успешно нашли тип элемента и его размер совпал со stride
        if element_type and element_type.width == stride:
            # Результатом операции "&array[index]" ВСЕГДА будет УКАЗАТЕЛЬ на этот элемент
            return Type.pointer(arch, element_type)

    # 5. РЕЗЕРВНЫЙ ВАРИАНТ (Если тип базы равен None или это просто сырой int/DWORD)
    # Если Binary Ninja не знает тип базы, мы ищем структуру по размеру stride в глобальной базе
    if stride > 0:
        for type_name, t in bv.types.items():
            if t.type_class == TypeClass.StructureTypeClass and t.width == stride:
                # Нашли структуру нужного размера? Возвращаем УКАЗАТЕЛЬ на неё!
                return Type.pointer(arch, t)

    return None


def change_type_operation_assign(func, dest, src):
    # Проверка что запись идет в переменную, а не по адрему или в поле стрктуры.
    if dest.operation != HighLevelILOperation.HLIL_VAR:
        return

    target_var = dest.var
    # Проверяем, что переменная полностью переписывается (не читается справа)
    if target_var in src.vars_read:
        return

    # Получаем текущий тип левой переменной
    left_type = dest.expr_type
    if left_type is None:
        return

    # проверяем что переменная это void*
    is_void_pointer = (left_type.type_class == TypeClass.PointerTypeClass and
                       left_type.target.type_class == TypeClass.VoidTypeClass)
    if not is_void_pointer:
        return

    right_type = None
    # 1. Если справа находится вызов функции (HLIL_CALL)
    if src.operation in [HighLevelILOperation.HLIL_CALL, HighLevelILOperation.HLIL_TAILCALL]:
        right_type = get_call_return_type(src)
    else:
        # Получаем тип выражения справа
        right_type = src.expr_type
        if right_type is None:
            return

        # Проверяем, является ли тип указателем
        is_right_pointer = right_type.type_class == TypeClass.PointerTypeClass
        if not is_right_pointer:
            return

    if right_type is None:
        return

    # проверяем что переменная это void*
    is_void_pointer = (right_type.type_class == TypeClass.PointerTypeClass and
                       right_type.target.type_class == TypeClass.VoidTypeClass)
    if is_void_pointer:
        return

    func.create_user_var(target_var, right_type, target_var.name)


def change_type_operation_variable_init(func, dest, src):
    target_var = dest
    # Проверяем, что переменная полностью переписывается (не читается справа)
    if target_var in src.vars_read:
        return

    # Получаем текущий тип левой переменной
    left_type = target_var.type
    if left_type is None:
        return

    # проверяем что переменная это void*
    is_void_pointer = (left_type.type_class == TypeClass.PointerTypeClass and
                       left_type.target.type_class == TypeClass.VoidTypeClass)
    if not is_void_pointer:
        return

    right_type = None
    # Если справа находится вызов функции
    if src.operation in [HighLevelILOperation.HLIL_CALL, HighLevelILOperation.HLIL_TAILCALL]:
        right_type = get_call_return_type(src)
    elif src.operation == HighLevelILOperation.HLIL_ADD:
        right_type = get_type_from_array_math(src)
    else:
        # Получаем тип выражения справа
        right_type = src.expr_type
        if right_type is None:
            return

        # Проверяем, является ли тип указателем
        is_right_pointer = right_type.type_class == TypeClass.PointerTypeClass
        if not is_right_pointer:
            return

    if right_type is None:
        return

    # проверяем что переменная это void*
    is_void_pointer = (right_type.type_class == TypeClass.PointerTypeClass and
                       right_type.target.type_class == TypeClass.VoidTypeClass)
    if is_void_pointer:
        return

    func.create_user_var(target_var, right_type, target_var.name)

    print(f'{dest=}, {src=}, {right_type=}')


def start_check_function(func, hlil):
    print(f'START CHECK FUNCTION: {func.name}')

    for block in hlil:
        for instr in block:
            # if instr.operation not in [HighLevelILOperation.HLIL_ASSIGN, HighLevelILOperation.HLIL_VAR_INIT]:
            #     continue

            if instr.operation == HighLevelILOperation.HLIL_ASSIGN:
                change_type_operation_assign(func, instr.dest, instr.src)
            elif instr.operation == HighLevelILOperation.HLIL_VAR_INIT:
                change_type_operation_variable_init(func, instr.dest, instr.src)



            # # 2. Проверяем, что СЛЕВА находится именно чистая переменная
            # if dest.operation == HighLevelILOperation.HLIL_VAR:
            #     target_var = dest.var
            #     var_name = target_var.name
            #
            #     # 3. Безопасность: проверяем, используется ли эта переменная СПРАВА от знака "="
            #     # Свойство vars_read возвращает список всех переменных, которые читаются в узле src
            #     if target_var in src.vars_read:
            #         # Это инкремент/модификация (например: x = x + 1 или x = x * 2). Пропускаем!
            #         continue
            #
            #     # 4. Если мы здесь, значит переменная ПОЛНОСТЬЮ переписывается новым значением
            #     print(f"[ПОЛНОЕ ПЕРЕПИСЫВАНИЕ] Адрес: {hex(instr.address)}")
            #     print(f"  -> Инструкция: '{instr}'")
            #     print(f"  -> Переменная: '{var_name}' (Тип в BN: {dest.expr_type})")
            #     print(f"  -> Правая часть (src.operation): {src.operation.name}")
            #     print("-" * 50)


def start_check_function_by_address(address):
    func = bv.get_function_at(address)
    if not func:
        return

    hlil = func.hlil
    if not hlil:
        return

    start_check_function(func, hlil)


def start_check_all_functions():
    for func in bv.functions:
        hlil = func.hlil
        if not hlil:
            continue

        start_check_function(func, hlil)


print('START SCRIPT')
bv.begin_undo_actions()

for i in range(4):
    start_check_all_functions()
# start_check_function_by_address(0x005DCF60)

bv.commit_undo_actions()
print('END SCRIPT')
