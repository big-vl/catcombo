import asyncio
import argparse
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakDBusError
from PIL import Image


class BLEPrinter:
    def __init__(self, target_name="LX-D02", black_level=9):
        self.target_name = target_name
        self.address = None
        self.char_uuid = "0000ffe1-0000-1000-8000-00805f9b34fb"
        self.notify_uuid = "0000ffe2-0000-1000-8000-00805f9b34fb"
        self.client = None
        self.ready_to_print = asyncio.Event()
        self.pause_required = asyncio.Event()
        self.is_printed = False  # 5a0600c10100000000000000 принтер готов к печати
        self.latest_notification = ""
        self.black_level = black_level
        # Команды для работы с принтером
        self.commands = [
            ("5a0100000000000000000000", "5a010003c00000001b965a00"),  # Инициализация
            (self.set_black_level(self.black_level), "5a0c"),  # Параметр черного
        ]

    async def find_and_connect(self):
        try:
            """
            Ищет устройство Bluetooth по имени и подключается к нему.

            :param target_name: Имя целевого устройства.
            """
            print("Поиск устройств Bluetooth...")
            devices = await BleakScanner.discover()
            target_name = self.target_name
            for device in devices:
                print(f"Найдено устройство: {device.name} [{device.address}]")
                if device.name == target_name:
                    self.address = device.address  # Устанавливаем адрес устройства
                    print(f"Устройство '{target_name}' найдено. Подключаемся...")
                    await self.connect(device.address)
                    return
            raise Exception(f"Устройство с именем '{target_name}' не найдено.")
        except BleakDBusError as e:
            raise Exception(f"Bluetooth выключен или не доступен. {e}")

    def set_black_level(self, level):
        """
        Устанавливает уровень черного для принтера.

        !!! Высокий уровень термпопринтера приводит к ошибке
        :param level: Значение от 0 до 7, где 0 - минимальный уровень, 9 - максимальный уровень.
        :return: Команда в формате HEX.
        """
        if not (0 <= level <= 9):
            raise ValueError("Уровень должен быть в диапазоне от 0 до 9.")
        return f"5a0c{level:02x}"

    async def connect(self, address):
        """Подключается к принтеру."""
        self.address = address
        self.client = BleakClient(self.address)
        await self.client.connect()
        cccd_handle = await self.find_cccd_handle(self.char_uuid)
        if not self.client.is_connected:
            raise ConnectionError("Не удалось подключиться к принтеру.")

        print("Принтер подключен.")

        # Подписываемся на уведомления
        await self.client.start_notify(self.notify_uuid, self.notification_handler)
        print("Подписка на уведомления установлена.")

    async def disconnect(self):
        """Отключается от принтера."""
        if self.client and self.client.is_connected:
            await self.client.stop_notify(self.notify_uuid)
            await self.client.disconnect()
            print("Принтер отключен.")

    async def find_cccd_handle(self, char_uuid):
        """Функция для поиска дескриптора CCCD по UUID характеристики"""
        services = await self.client.get_services()
        for service in services:
            for char in service.characteristics:
                print("char", char)
                if char.uuid.lower() == char_uuid.lower():
                    for descriptor in char.descriptors:
                        # Проверяем UUID дескриптора CCCD (0x2902)
                        print("descriptor", descriptor)
                        if (
                            descriptor.uuid.lower()
                            == "00002902-0000-1000-8000-00805f9b34fb"
                        ):
                            return descriptor.handle

    def notification_handler(self, sender, data):
        """Обработчик уведомлений от принтера."""
        data_hex = data.hex()
        print(f"Получено уведомление от {sender}: {data_hex}")
        self.latest_notification = data_hex

        # Проверяем уровень заряда батареи
        if data_hex.startswith("5a02") and len(data_hex) >= 6:  # Убедимся, что длина данных достаточна
            battery_byte = data_hex[4:6]  # Извлекаем третий байт (2 символа, начиная с индекса 4)
            battery_level = int(battery_byte, 16)  # Преобразуем из hex в десятичное значение

            # Определяем уровень заряда в процентах
            if 0x00 <= battery_level <= 0x64:  # Диапазон значений для уровня заряда
                battery_percentage = (battery_level * 100) // 0x64
            else:
                battery_percentage = None  # Неопределенный диапазон

            # Проверяем состояние зарядки
            if len(data_hex) >= 10:  # Убедимся, что длина данных достаточна
                charging_status_byte = data_hex[8:10]  # Извлекаем пятый байт (2 символа, начиная с индекса 8)
                if charging_status_byte == "01":
                    print("Идет заряд батареи...")

            if battery_percentage is not None:
                print(f"Уровень заряда батареи: {battery_percentage}%")
            else:
                print(f"Неизвестный уровень заряда батареи: {battery_byte}")

        if data_hex.startswith("5a0714"):
            print("Принтер требует паузы.")
            self.pause_required.set()
        elif data_hex.startswith("5a0b01"):
            print("Принтер готов к печати.")
            self.ready_to_print.set()

    async def send_packets(self, packets_hex):
        command_start_print = [
            ("5a0a2e58f6181b79f1075dc3", "5a0a"),
            ("5a0bdefb0c26fe2d159b822c", "5a0b"),
        ]
        for command, expected_prefix in command_start_print:
            print("Отправка команды/префикс:", command, expected_prefix)
            await self.send_command(command, expected_prefix)

        start_line, end_line = self.generate_hex_string_len(packets_hex)
        packets = self.validate_and_correct_line_numbers(packets_hex)
        max_packet = len(packets)
        for idx, hex_data in enumerate(packets):
            try:
                # Проверяем, нужно ли сделать паузу
                if self.pause_required.is_set():
                    print("Пауза на 59 мс...")
                    await asyncio.sleep(0.59)  # Пауза 59 мс
                    self.pause_required.clear()  # Сбрасываем флаг паузы

                if idx == 0:
                    await self.client.write_gatt_char(self.char_uuid, start_line)
                    await asyncio.sleep(0.1)
                elif idx == max_packet:
                    await self.client.write_gatt_char(self.char_uuid, end_line)
                    await asyncio.sleep(0.1)

                # Преобразуем данные в байты
                data = bytearray.fromhex(hex_data)

                # Отправляем данные на принтер
                await self.client.write_gatt_char(self.char_uuid, data)
                print(
                    f"[{idx}/{len(packets_hex)}] Отправлен {len(data)}-байтный пакет: {hex_data[:40]}..."
                )

                # Основная пауза между отправкой пакетов
                await asyncio.sleep(0.04)

            except Exception as e:
                print(f"Ошибка при отправке пакета {idx+1}: {e}")
                break

    async def wait_for_print_completion(self):
        """
        Ожидает уведомления о завершении печати.
        """
        print("Ожидание завершения печати...")
        while True:
            await asyncio.sleep(0.1)
            if self.latest_notification.startswith("5a060"):
                print("Принтер завершил печать.")
                self.is_printed = False
                break

    async def send_command(self, command, expected_response_prefix):
        """Отправляет команду на принтер и ждёт ожидаемого ответа."""
        data = bytearray.fromhex(command)
        if self.client:
            await self.client.write_gatt_char(self.char_uuid, data)
            print(f"Отправлено: {command}")
            await asyncio.sleep(0.1)
            # Ждём ответа от принтера
            while True:
                await asyncio.sleep(0.2)
                if self.latest_notification.startswith(expected_response_prefix):
                    print(f"Получен ожидаемый ответ: {self.latest_notification}")
                    break

    def is_document(self, image):
        """
        Определяет, является ли изображение документом (текст, линии)
        или фотографией.
        """
        # Преобразуем изображение в оттенки серого
        grayscale_image = image.convert("L")

        # Получаем гистограмму яркости (0-255)
        histogram = grayscale_image.histogram()

        # Считаем, сколько пикселей попадает в яркость между 0 и 50 (тёмные) и 200-255 (светлые)
        dark_pixels = sum(histogram[:50])
        light_pixels = sum(histogram[200:])

        # Высокий контраст (много тёмных и светлых пикселей) характерен для документа
        if dark_pixels + light_pixels > 0.85 * sum(histogram):
            return True  # Это документ
        return False  # Это фотография

    def generate_printer_data(self, image_path, target_width=384):
        """
        Генерирует строки данных для печати с учётом полутонов через дизеринг.
        :param image_path: Путь к изображению.
        :param target_width: Ширина изображения для принтера (обычно 384 пикселя).
        :return: Список строк данных в формате HEX.
        """
        with Image.open(image_path) as img:

            # Преобразуем изображение в оттенки серого
            img = img.convert("L")

            # Масштабируем изображение до ширины принтера
            if img.width != target_width:
                new_height = int((target_width / img.width) * img.height)
                img = img.resize((target_width, new_height), Image.LANCZOS)

            if self.is_document(img):
                img = img.convert("1", dither=Image.NONE)
                img.save(".debug_images/debug_document_image.png")
                print("Промежуточный документ сохранен как debug_document_image.png")
            else:
                # Применяем дизеринг
                img = img.convert("1", dither=Image.FLOYDSTEINBERG)

                # Сохраняем для отладки
                img.save(".debug_images/debug_dithered_image.png")
                print(
                    "Промежуточное изображение с дизерингом сохранено как debug_dithered_image.png"
                )

            # Убедимся, что высота чётная
            if img.height % 2 != 0:
                img = img.crop((0, 0, img.width, img.height - 1))

            printer_width = img.width
            packets = []

            # Формируем данные для принтера
            for y in range(0, img.height, 2):
                upper_line = []
                lower_line = []

                for x in range(0, printer_width, 8):
                    upper_byte = 0
                    lower_byte = 0

                    for bit in range(8):
                        if x + bit < printer_width:
                            # Верхняя строка
                            if img.getpixel((x + bit, y)) == 0:  # Чёрный пиксель
                                upper_byte |= 1 << (7 - bit)
                            # Нижняя строка
                            if (
                                y + 1 < img.height and img.getpixel((x + bit, y + 1)) == 0
                            ):  # Чёрный пиксель
                                lower_byte |= 1 << (7 - bit)

                    upper_line.append(upper_byte)
                    lower_line.append(lower_byte)

                # Формируем HEX-строки
                upper_hex = "".join(f"{byte:02x}" for byte in upper_line)
                lower_hex = "".join(f"{byte:02x}" for byte in lower_line)

                packets.append(f"{upper_hex}{lower_hex}")

        return packets

    def validate_and_correct_line_numbers(self, packet_list):
        """
        Проверяет и корректирует нумерацию строк в массиве.

        :param packet_list: Список строк, содержащих пакеты данных (в формате HEX).
        :return: Исправленный список пакетов.
        """
        corrected_packets = []
        for idx, packet in enumerate(packet_list):
            if packet.startswith("55") and packet.endswith("00"):
                # Извлекаем текущий номер строки
                current_number = packet[2:6]
                expected_number = f"{idx:04x}"

                if current_number.lower() != expected_number:
                    print(
                        f"Исправление номера строки: {current_number} -> {expected_number}"
                    )
                    corrected_packet = f"55{expected_number}{packet[6:-2]}00"
                else:
                    corrected_packet = packet
            else:
                expected_number = f"{idx:04x}"
                corrected_packet = f"55{expected_number}{packet}00"

            corrected_packets.append(corrected_packet)

        return corrected_packets

        return True, "Нумерация строк корректна"

    def generate_hex_string_len(self, data_list):
        # Вычисляем количество записей в списке
        total_records = len(data_list) + 1

        # Преобразуем количество записей в 4-значное шестнадцатеричное число
        final_number = f"{total_records:04x}"

        # Префикс для сообщения
        prefix = "5a04"

        # Формируем начало и конец строки
        start_message = f"{prefix}{final_number}0000"
        end_message = f"{prefix}{final_number}0100"

        return bytearray.fromhex(start_message), bytearray.fromhex(end_message)

    async def print_image(self, image_path):
        """Печатает изображение."""
        packets = self.generate_printer_data(image_path)
        self.is_printed = True
        print("Начинаем печать изображения.")
        await self.send_packets(packets)
        await self.wait_for_print_completion()
        print("Печать завершена.")

    async def initialize(self):
        """Отправляет начальные команды принтеру."""
        print("Инициализация принтера...")
        for command, expected_prefix in self.commands:
            print("Отправка команды/префикс:", command, expected_prefix)
            await self.send_command(command, expected_prefix)

    async def ble_print_job(self, image_bytes):
        """Асинхронно подключается к принтеру и печатает"""
        if not self.client or not self.client.is_connected:
            print("Принтер не подключен. Подключаемся...")
            await self.find_and_connect()  # Асинхронный коннект
            await self.initialize()  # Отправляем начальные команды
        await self.print_image(image_bytes)
        # await ble_printer.disconnect()


async def main():
    parser = argparse.ArgumentParser(description="BLE Printer Script")
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        required=True,
        help="Путь к файлу изображения для печати",
    )
    parser.add_argument("--address", "-a", type=str, help="MAC-адрес принтера")
    parser.add_argument(
        "--black_level", "-b", type=int, default=7, help="Уровень черного (0-7)"
    )
    parser.add_argument(
        "--name", "-n", type=str, default="LX-D02", help="Имя Bluetooth устройства"
    )

    args = parser.parse_args()

    printer = BLEPrinter(black_level=args.black_level)
    if args.address is not None:
        await printer.connect(args.address)
    else:
        await printer.find_and_connect()
    try:
        await printer.initialize()
        await printer.print_image(args.file)
    finally:
        await printer.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
