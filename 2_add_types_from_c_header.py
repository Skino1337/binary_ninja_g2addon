from pathlib import Path
import json


current_file_path = Path(__file__).resolve()
current_file_folder = current_file_path.parent
HEADER_FILE_PATH = current_file_folder / 'c_header.h'
TYPES_SIZE_FILE_PATH = current_file_folder / 'types_size.json'
source_code = HEADER_FILE_PATH.read_text()
types_size = TYPES_SIZE_FILE_PATH.read_text()


result = bv.parse_types_from_string(source_code)
# result.types — словарь распарсенных структур, юнионов и typedef'ов.
# result.variables — глобальные переменные (если они были объявлены в строке).
# result.functions — сигнатуры функций.

bv.begin_undo_actions()

for name, type_object in result.types.items():
    bv.define_user_type(name, type_object)
    # print(f"[+] Добавлен тип: {name}")

bv.commit_undo_actions()

size_dict = json.loads(types_size)

# Получаем доступ к типам текущего бинарного файла
analysis_types = bv.types

print("=== СПИСОК ПОЛЬЗОВАТЕЛЬСКИХ ТИПОВ И ИХ РАЗМЕРЫ ===")
print(f"{'Имя типа':<40} | {'Размер (в байтах)':<15}")
print("=" * 60)

# Перебираем все зарегистрированные типы
for type_name, type_object in analysis_types.items():
    # Отсекаем встроенные примитивные типы (вроде int, char, void)
    # и оставляем только пользовательские структуры, typedef и перечисления
    if type_object.registered_name:
        try:
            # Получаем размер типа в байтах
            type_size = type_object.width
            # type_name может быть объектом QualifiedName, приводим к строке
            name_str = str(type_name)
            if name_str in size_dict:
                if not name_str.endswith('_vtable'):
                    if name_str not in ['', ]: # zCCollObjectCharacter
                        size_from_header = size_dict[name_str]
                        if type_size != size_from_header:
                            print(f"{name_str:<40} | {hex(type_size):<8} | {hex(size_from_header):<8}")
        except Exception as e:
            # Некоторые типы (например, неполные структуры) могут не иметь фиксированного размера
            print(f"{str(type_name):<40} | Ошибка: {e}")

print("=" * 60)
print('END SCRIPT')