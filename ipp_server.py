import io
import time
import struct
import logging
import socketserver
import itertools
import operator
import random
import asyncio
import threading
from http.server import BaseHTTPRequestHandler
from io import BytesIO

from wand.image import Image
from wand.color import Color

from main import BLEPrinter

# Создаем глобальный event loop для BLE операций
ble_loop = asyncio.new_event_loop()


def start_ble_loop():
    asyncio.set_event_loop(ble_loop)
    ble_loop.run_forever()


def schedule_ble_print_job(ble_printer, image_bytes):
    # Планируем выполнение ble_print_job в нашем ble_loop
    future = asyncio.run_coroutine_threadsafe(
        ble_printer.ble_print_job(image_bytes), ble_loop
    )
    # Ожидаем завершения задачи и возвращаем результат (если необходимо)
    return future.result()


# =====================
# Вспомогательные функции
# =====================


def pack_bool(val: bool) -> bytes:
    """Упаковывает bool в 1 байт (0 или 1)."""
    return struct.pack(">b", 1 if val else 0)


def pack_int(val: int) -> bytes:
    """Упаковывает int в 4 байта (Big-endian)."""
    return struct.pack(">i", val)


def pack_enum(val: int) -> bytes:
    """То же самое, что и int, но семантически используется для enum."""
    return pack_int(val)


# =====================
# Чтение PPD-файла
# =====================


class BasicPostscriptPPD:
    def __init__(self, filename):
        self.filename = filename

    def text(self):
        with open(self.filename, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


# =====================
# Стандартные enum-коды для IPP
# =====================

from enum import IntEnum


class SectionEnum(IntEnum):
    # delimiters (sections)
    SECTIONS = 0x00
    SECTIONS_MASK = 0xF0
    operation = 0x01
    job = 0x02
    END = 0x03
    printer = 0x04
    unsupported = 0x05

    @classmethod
    def is_section_tag(cls, tag):
        return (tag & cls.SECTIONS_MASK) == cls.SECTIONS


class TagEnum(IntEnum):
    unsupported_value = 0x10
    unknown_value = 0x12
    no_value = 0x13

    # int types
    integer = 0x21
    boolean = 0x22
    enum = 0x23

    # string types
    octet_str = 0x30
    datetime_str = 0x31
    resolution = 0x32
    range_of_integer = 0x33
    text_with_language = 0x35
    name_with_language = 0x36

    text_without_language = 0x41
    name_without_language = 0x42
    keyword = 0x44
    uri = 0x45
    uri_scheme = 0x46
    charset = 0x47
    natural_language = 0x48
    mime_media_type = 0x49


class StatusCodeEnum(IntEnum):
    # https://tools.ietf.org/html/rfc2911#section-13.1
    ok = 0x0000
    server_error_internal_error = 0x0500
    server_error_operation_not_supported = 0x0501
    server_error_job_canceled = 0x508


class OperationEnum(IntEnum):
    # https://tools.ietf.org/html/rfc2911#section-4.4.15
    print_job = 0x0002
    validate_job = 0x0004
    cancel_job = 0x0008
    get_job_attributes = 0x0009
    get_jobs = 0x000A
    get_printer_attributes = 0x000B

    # 0x4000 - 0xFFFF is for extensions (например CUPS)
    cups_get_default = 0x4001
    cups_list_all_printers = 0x4002


class JobStateEnum(IntEnum):
    # https://tools.ietf.org/html/rfc2911#section-4.3.7
    pending = 3
    pending_held = 4
    processing = 5
    processing_stopped = 6
    canceled = 7
    aborted = 8
    completed = 9


# =====================
# Класс, описывающий запрос/ответ IPP
# =====================


class IppRequest(object):
    def __init__(self, version, opid_or_status, request_id, attributes):
        self.version = version  # (major, minor)
        self.opid_or_status = opid_or_status
        self.request_id = request_id
        self._attributes = attributes

    def __repr__(self):
        return "IppRequest(%r, 0x%04x, 0x%02x, %r)" % (
            self.version,
            self.opid_or_status,
            self.request_id,
            self._attributes,
        )

    @classmethod
    def from_string(cls, string):
        return cls.from_file(BytesIO(string))

    @classmethod
    def from_file(cls, f):
        # 2 байта (версия), 2 байта (операция/статус), 4 байта (request_id)
        version = cls.read_struct(f, b">bb")  # (major, minor)
        operation_id_or_status_code, request_id = cls.read_struct(f, b">hi")

        attributes = {}
        current_section = None
        current_name = None
        while True:
            (tag,) = cls.read_struct(f, b">B")

            if tag == SectionEnum.END:
                break
            elif SectionEnum.is_section_tag(tag):
                current_section = tag
                current_name = None
            else:
                if current_section is None:
                    raise Exception("No section delimiter")

                (name_len,) = cls.read_struct(f, b">h")
                if name_len == 0:
                    if current_name is None:
                        raise Exception("Additional attribute needs a name to follow")
                    # дополнительный атрибут с тем же именем
                else:
                    current_name = f.read(name_len)

                (value_len,) = cls.read_struct(f, b">h")
                value_str = f.read(value_len)
                attributes.setdefault((current_section, current_name, tag), []).append(
                    value_str
                )

        return cls(version, operation_id_or_status_code, request_id, attributes)

    @staticmethod
    def read_struct(f, fmt):
        sz = struct.calcsize(fmt)
        string = f.read(sz)
        return struct.unpack(fmt, string)

    @staticmethod
    def write_struct(f, fmt, *args):
        data = struct.pack(fmt, *args)
        f.write(data)

    def to_string(self):
        sio = BytesIO()
        self.to_file(sio)
        return sio.getvalue()

    def to_file(self, f):
        # Запись версии
        version_major, version_minor = 1, 1
        self.write_struct(f, b">bb", version_major, version_minor)
        # Запись кода операции/статуса + request_id
        self.write_struct(f, b">hi", self.opid_or_status, self.request_id)

        # Группируем по секциям (operation/job/printer)
        for section, attrs_in_section in itertools.groupby(
            sorted(self._attributes.keys()), operator.itemgetter(0)
        ):
            self.write_struct(f, b">B", section)
            for key in attrs_in_section:
                _section, name, tag = key
                for i, value in enumerate(self._attributes[key]):
                    self.write_struct(f, b">B", tag)
                    if i == 0:
                        self.write_struct(f, b">h", len(name))
                        f.write(name)
                    else:
                        self.write_struct(f, b">h", 0)
                    self.write_struct(f, b">h", len(value))
                    f.write(value)
        self.write_struct(f, b">B", SectionEnum.END)


# =====================
# Основная логика IPP-принтера
# =====================


def get_job_id(req):
    """Пример функции, чтобы достать job-id из атрибутов запроса (необязательно)."""
    # Здесь можно пропарсить req._attributes
    return 1


class IPPPrinterMethod:
    """A minimal printer which implements all the things a printer needs to work."""

    def __init__(self):
        super().__init__()

    def get_handle_command_function(self, opid_or_status):
        commands = {
            OperationEnum.get_printer_attributes: self.operation_printer_list_response,
            OperationEnum.cups_list_all_printers: self.operation_printer_list_response,
            OperationEnum.cups_get_default: self.operation_printer_list_response,
            OperationEnum.validate_job: self.operation_validate_job_response,
            OperationEnum.get_jobs: self.operation_get_jobs_response,
            OperationEnum.get_job_attributes: self.operation_get_job_attributes_response,
            OperationEnum.print_job: self.operation_print_job_response,
            0x0D0A: self.operation_misidentified_as_http,
        }

        try:
            command_function = commands[opid_or_status]
        except KeyError:
            logging.warning("Operation not supported 0x%04x", opid_or_status)
            command_function = self.operation_not_implemented_response
        return command_function

    def operation_not_implemented_response(self, req, _psfile):
        attributes = self.minimal_attributes()
        return IppRequest(
            self.version,
            StatusCodeEnum.server_error_internal_error,
            req.request_id,
            attributes,
        )

    def operation_printer_list_response(self, req, _psfile):
        attributes = self.printer_list_attributes()
        return IppRequest(self.version, StatusCodeEnum.ok, req.request_id, attributes)

    def operation_validate_job_response(self, req, _psfile):
        # TODO: здесь просто возвращается ОК
        attributes = self.minimal_attributes()
        return IppRequest(self.version, StatusCodeEnum.ok, req.request_id, attributes)

    def operation_get_jobs_response(self, req, _psfile):
        # Пустой список заданий
        attributes = self.minimal_attributes()
        return IppRequest(self.version, StatusCodeEnum.ok, req.request_id, attributes)

    def operation_print_job_response(self, req, psfile):
        job_id = self.create_job(req)
        attributes = self.print_job_attributes(
            job_id, JobStateEnum.pending, [b"job-incoming", b"job-data-insufficient"]
        )
        self.handle_postscript(req, psfile)
        return IppRequest(self.version, StatusCodeEnum.ok, req.request_id, attributes)

    def operation_get_job_attributes_response(self, req, _psfile):
        job_id = get_job_id(req)
        attributes = self.print_job_attributes(
            job_id, JobStateEnum.completed, [b"none"]
        )
        return IppRequest(self.version, StatusCodeEnum.ok, req.request_id, attributes)

    def operation_misidentified_as_http(self, _req, _psfile):
        raise Exception("Request был, похоже, HTTP, т.к. содержит 0x0d0a (\\r\\n).")

    def minimal_attributes(self):
        """Минимальный набор атрибутов для ответа."""
        return {
            # RFC2911 раздел 3.1.4.2
            (SectionEnum.operation, b"attributes-charset", TagEnum.charset): [b"utf-8"],
            (
                SectionEnum.operation,
                b"attributes-natural-language",
                TagEnum.natural_language,
            ): [b"en"],
        }

    def printer_list_attributes(self):
        """Атрибуты принтера для get_printer_attributes."""
        attr = {
            (SectionEnum.printer, b"printer-uri-supported", TagEnum.uri): [
                self.printer_uri
            ],
            (SectionEnum.printer, b"uri-authentication-supported", TagEnum.keyword): [
                b"none"
            ],
            (SectionEnum.printer, b"uri-security-supported", TagEnum.keyword): [
                b"none"
            ],
            (SectionEnum.printer, b"printer-name", TagEnum.name_without_language): [
                self.printer_name
            ],
            (SectionEnum.printer, b"printer-info", TagEnum.text_without_language): [
                self.printer_name
            ],
            (
                SectionEnum.printer,
                b"printer-make-and-model",
                TagEnum.text_without_language,
            ): [self.printer_name],
            (SectionEnum.printer, b"printer-state", TagEnum.enum): [
                pack_enum(3)
            ],  # 3 = idle
            (SectionEnum.printer, b"printer-state-reasons", TagEnum.keyword): [b"none"],
            (SectionEnum.printer, b"ipp-versions-supported", TagEnum.keyword): [b"1.1"],
            (SectionEnum.printer, b"operations-supported", TagEnum.enum): [
                pack_enum(x)
                for x in (
                    OperationEnum.print_job,
                    OperationEnum.validate_job,
                    OperationEnum.cancel_job,
                    OperationEnum.get_job_attributes,
                    OperationEnum.get_printer_attributes,
                )
            ],
            (
                SectionEnum.printer,
                b"multiple-document-jobs-supported",
                TagEnum.boolean,
            ): [pack_bool(False)],
            (SectionEnum.printer, b"charset-configured", TagEnum.charset): [b"utf-8"],
            (SectionEnum.printer, b"charset-supported", TagEnum.charset): [b"utf-8"],
            (
                SectionEnum.printer,
                b"natural-language-configured",
                TagEnum.natural_language,
            ): [b"en"],
            (
                SectionEnum.printer,
                b"generated-natural-language-supported",
                TagEnum.natural_language,
            ): [b"en"],
            (
                SectionEnum.printer,
                b"document-format-default",
                TagEnum.mime_media_type,
            ): [b"application/pdf"],
            (
                SectionEnum.printer,
                b"document-format-supported",
                TagEnum.mime_media_type,
            ): [b"application/pdf"],
            (SectionEnum.printer, b"printer-is-accepting-jobs", TagEnum.boolean): [
                pack_bool(True)
            ],
            (SectionEnum.printer, b"queued-job-count", TagEnum.integer): [pack_int(0)],
            (SectionEnum.printer, b"pdl-override-supported", TagEnum.keyword): [
                b"not-attempted"
            ],
            (SectionEnum.printer, b"printer-up-time", TagEnum.integer): [
                pack_int(self.printer_uptime())
            ],
            (SectionEnum.printer, b"compression-supported", TagEnum.keyword): [b"none"],
            (SectionEnum.printer, b"media-supported", TagEnum.keyword): [b"roll_57mm"],
            (SectionEnum.printer, b"media-default", TagEnum.keyword): [b"roll_57mm"],
            (SectionEnum.printer, b"printer-uuid", TagEnum.uri): [self.printer_uuid],
        }
        attr.update(self.minimal_attributes())
        return attr

    def print_job_attributes(self, job_id, state, state_reasons):
        """Атрибуты конкретной печатной задачи (job)."""
        job_uri = b"%sjob/%d" % (self.base_uri, job_id)
        attr = {
            (SectionEnum.operation, b"job-uri", TagEnum.uri): [job_uri],
            (SectionEnum.operation, b"job-id", TagEnum.integer): [pack_int(job_id)],
            (SectionEnum.operation, b"job-state", TagEnum.enum): [pack_enum(state)],
            (
                SectionEnum.operation,
                b"job-state-reasons",
                TagEnum.keyword,
            ): state_reasons,
            (SectionEnum.operation, b"job-printer-uri", TagEnum.uri): [
                self.printer_uri
            ],
            (SectionEnum.operation, b"job-name", TagEnum.name_without_language): [
                b"Print job %d" % job_id
            ],
            (
                SectionEnum.operation,
                b"job-originating-user-name",
                TagEnum.name_without_language,
            ): [b"job-originating-user-name"],
            (SectionEnum.operation, b"time-at-creation", TagEnum.integer): [
                pack_int(0)
            ],
            (SectionEnum.operation, b"time-at-processing", TagEnum.integer): [
                pack_int(0)
            ],
            (SectionEnum.operation, b"time-at-completed", TagEnum.integer): [
                pack_int(0)
            ],
            (SectionEnum.operation, b"job-printer-up-time", TagEnum.integer): [
                pack_int(self.printer_uptime())
            ],
        }
        attr.update(self.minimal_attributes())
        return attr

    def printer_uptime(self):
        return int(time.time())

    def create_job(self, req):
        # Возвращаем случайный job_id
        return random.randint(1, 9999)

    def is_document(self, image, dark_threshold=50, light_threshold=200):
        """
        Проверяет, является ли изображение документом на основе гистограммы.
        :param image: Объект изображения (Wand Image).
        :param dark_threshold: Порог яркости для тёмных пикселей.
        :param light_threshold: Порог яркости для светлых пикселей.
        :return: True, если это документ; False, если это фотография.
        """
        # Убедимся, что изображение в режиме grayscale
        with image.clone() as grayscale_img:
            grayscale_img.type = "grayscale"

            # Получаем гистограмму (преобразуем значения в числа)
            histogram = [int(color.red) for color in grayscale_img.histogram]

            # Считаем общее количество пикселей
            total_pixels = sum(histogram)

            # Проверяем, есть ли пиксели вообще
            if total_pixels == 0:
                print("Гистограмма пустая: невозможно определить тип изображения.")
                return False  # Считаем, что это не документ

            # Считаем тёмные и светлые пиксели
            dark_pixels = sum(
                histogram[:dark_threshold]
            )  # Пиксели с яркостью 0–dark_threshold
            light_pixels = sum(
                histogram[light_threshold:]
            )  # Пиксели с яркостью light_threshold–255

            # Определяем, является ли изображение документом
            if (dark_pixels + light_pixels) / total_pixels > 0.85:
                return True  # Это документ
            return False  # Это фотография

    def handle_postscript(
        self, ipp_request, postscript_file, black_threshold=40, resolution=300
    ):
        # 1) Считываем всё содержимое из postscript_file (PS) в память
        raw_data = postscript_file.read()

        # Открываем весь PostScript документ как многостраничное изображение
        with Image(blob=raw_data, resolution=resolution) as original_doc:
            print(f"Количество страниц: {len(original_doc.sequence)}")

            # Если несколько страниц - считаем, что это документ
            page_count = len(original_doc.sequence)
            is_multi_page = page_count > 1

            # Итерация по каждой странице документа
            for page_index, page in enumerate(original_doc.sequence):
                print(f"Обработка страницы {page_index + 1}")

                # Создаем объект Image для текущей страницы
                with Image(image=page) as original_img:
                    original_img.trim()

                    # Проверка, является ли страница документом для обрезки
                    if is_multi_page or self.is_document(original_img):
                        print(
                            "Изображение распознано как документ. Выполняется обрезка."
                        )

                        # Создаем копию для анализа в режиме grayscale
                        with original_img.clone() as grayscale_img:
                            grayscale_img.type = "grayscale"
                            width, height = grayscale_img.width, grayscale_img.height

                            # Экспортируем пиксели для анализа
                            pixels = grayscale_img.export_pixels(
                                x=0, y=0, width=width, height=height, channel_map="I"
                            )

                            # Инициализация координат крайних чёрных точек
                            min_x, max_x = width, 0
                            min_y, max_y = height, 0

                            # Поиск чёрных пикселей
                            for y in range(height):
                                for x in range(width):
                                    index = y * width + x
                                    intensity = pixels[index]
                                    if (
                                        intensity < black_threshold
                                    ):  # Порог яркости для чёрных пикселей
                                        if x < min_x:
                                            min_x = x
                                        if x > max_x:
                                            max_x = x
                                        if y < min_y:
                                            min_y = y
                                        if y > max_y:
                                            max_y = y

                            # Проверяем, были ли найдены чёрные пиксели
                            if min_x <= max_x and min_y <= max_y:
                                # Рассчитываем новые размеры для обрезки
                                crop_width = max_x - min_x + 1
                                crop_height = max_y - min_y + 1

                                # Обрезаем оригинальное изображение по рассчитанным координатам
                                original_img.crop(
                                    left=min_x,
                                    top=min_y,
                                    width=crop_width,
                                    height=crop_height,
                                )
                                print(
                                    f"Страница {page_index + 1}: Обрезка изображения до: {crop_width}x{crop_height}, координаты: ({min_x}, {min_y})"
                                )
                            else:
                                print(
                                    f"Страница {page_index + 1}: Чёрные пиксели не найдены; обрезка не требуется."
                                )
                    else:
                        print(
                            f"Страница {page_index + 1}: Изображение распознано как фотография. Обрезка не выполняется."
                        )

                    # Сохраняем обработанную страницу в памяти как PNG для отправки
                    original_img.format = "png"
                    # (Необязательно) Сохраняем для отладки на диск
                    debug_filename = (
                        f".debug_images/debug_cropped_image_page_{page_index + 1}.png"
                    )
                    original_img.save(filename=debug_filename)
                    print(
                        f"Страница {page_index + 1}: Изображение после обрезки сохранено как {debug_filename}"
                    )

                    # Получаем PNG-байты текущей страницы
                    png_bytes = BytesIO(original_img.make_blob("png"))

                    # 3) Передаём эти байты в асинхронный метод BLEPrinter
                    schedule_ble_print_job(self.ble_printer, png_bytes)
                    print(
                        f"Страница {page_index + 1}: Файл конвертирован в PNG и отправлен на печать..."
                    )


# =====================
# Обработчик запросов HTTP/IPP
# =====================


class IPPRequestHandler(BaseHTTPRequestHandler):
    default_request_version = "HTTP/1.1"
    protocol_version = "HTTP/1.1"

    @staticmethod
    def _get_next_chunk(rfile):
        while True:
            chunk_size_s = rfile.readline()
            logging.debug("chunksz=%r", chunk_size_s)
            if not chunk_size_s:
                raise RuntimeError("Socket closed in the middle of a chunked request")
            if chunk_size_s.strip() != b"":
                break
        chunk_size = int(chunk_size_s, 16)
        if chunk_size == 0:
            return b""
        chunk = rfile.read(chunk_size)
        logging.debug("chunk=0x%x", len(chunk))
        return chunk

    @staticmethod
    def read_chunked(rfile):
        while True:
            chunk = IPPRequestHandler._get_next_chunk(rfile)
            if chunk == b"":
                rfile.close()
                break
            else:
                yield chunk

    def parse_request(self):
        ret = BaseHTTPRequestHandler.parse_request(self)
        if "chunked" in self.headers.get("transfer-encoding", ""):
            self.rfile = BytesIO(b"".join(self.read_chunked(self.rfile)))
        self.close_connection = True
        return ret

    # Совместимость со старыми версиями Python, где нет send_response_only
    if not hasattr(BaseHTTPRequestHandler, "send_response_only"):

        def send_response_only(self, code, message=None):
            if message is None:
                if code in self.responses:
                    message = self.responses[code][0]
                else:
                    message = ""
            if not hasattr(self, "_headers_buffer"):
                self._headers_buffer = []
            self._headers_buffer.append(
                ("%s %d %s\r\n" % (self.protocol_version, code, message)).encode(
                    "latin-1", "strict"
                )
            )

    def log_error(self, format, *args):
        logging.error(format, *args)

    def log_message(self, format, *args):
        logging.debug(format, *args)

    def send_headers(self, status=200, content_type="text/plain", content_length=None):
        self.log_request(status)
        self.send_response_only(status, None)
        self.send_header("Server", "ipp-server")
        self.send_header("Date", self.date_time_string())
        self.send_header("Content-Type", content_type)
        if content_length:
            self.send_header("Content-Length", "%u" % content_length)
        self.send_header("Connection", "close")
        self.end_headers()

    def do_POST(self):
        self.handle_ipp()

    def do_GET(self):
        self.handle_www()

    def handle_www(self):
        if self.path == "/":
            self.send_headers(status=200, content_type="text/plain")
            self.wfile.write(b"IPP server is running ...")
        elif self.path.endswith(".ppd"):
            self.send_headers(status=200, content_type="text/plain")
            self.wfile.write(
                self.server.postscript.ppd.text().encode("utf-8", errors="ignore")
            )
        else:
            self.send_headers(status=404, content_type="text/plain")
            self.wfile.write(b"404 Not Found")

    def handle_expect_100(self):
        """Отключаем это поведение, пусть всегда ок."""
        return True

    def handle_ipp(self):
        # Читаем IPP-запрос
        self.ipp_request = IppRequest.from_file(self.rfile)

        if self.server.postscript.expect_page_data_follows(self.ipp_request):
            self.send_headers(status=100, content_type="application/ipp")
            postscript_file = None
        else:
            postscript_file = self.rfile

        ipp_response = self.server.postscript.handle_ipp(
            self.ipp_request, postscript_file
        ).to_string()

        self.send_headers(
            status=200, content_type="application/ipp", content_length=len(ipp_response)
        )
        self.wfile.write(ipp_response)


# =====================
# Реализация методов IPP в наследнике
# =====================


class PostscriptHandler(IPPPrinterMethod):
    """Пример реализации принтера, куда можно вставить свою логику печати."""

    version = (1, 1)

    def __init__(self, connection_params):
        self.uri = "ipp://192.168.0.100:8095/"
        self.name = "Thermal Printer LX-D2 57mm 203 DPI"
        self.base_uri = self.uri.encode("ascii")
        self.printer_uri = (self.uri + "ipp/print").encode("ascii")
        self.printer_name = self.name.encode("ascii")
        self.printer_uuid = (
            "urn:uuid:" + "884d7c0a-f449-45a7-8bbe-095e2943d313"
        ).encode("ascii")
        self.connection_params = connection_params
        self.printer_connection = self.connect_to_printer(connection_params)
        # PPD
        self.pdd = BasicPostscriptPPD("pdd/LX-D2-thermal_57mm_203dpi.ppd")
        self.ble_printer = self.connect_to_printer(self.name)

    def connect_to_printer(self, connection_params):
        # Логика подключения к физическому принтеру или драйверу
        ble_printer = BLEPrinter()
        return ble_printer

    def expect_page_data_follows(self, ipp_request):
        # Возвращает True, если ожидаются ещё данные (PS, PDF и т.п.)
        return False

    def handle_ipp(self, ipp_request, postscript_file):
        command_function = self.get_handle_command_function(ipp_request.opid_or_status)
        logging.debug(
            "IPP %r -> %s.%s",
            ipp_request.opid_or_status,
            type(self).__name__,
            command_function.__name__,
        )
        return command_function(ipp_request, postscript_file)

    @property
    def ppd(self):
        # Можно возвращать другую логику, если нужно
        return BasicPostscriptPPD("pdd/LX-D2-thermal_57mm_203dpi.ppd")


# =====================
# Сервер IPP
# =====================


class IPPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True

    def __init__(self, address, request_handler, postscript):
        self.postscript = postscript
        super().__init__(address, request_handler)


def run_server(host="0.0.0.0", port=6310):
    logging.basicConfig(level=logging.DEBUG)
    connection_params = (host, port)
    server = IPPServer(
        (host, port), IPPRequestHandler, PostscriptHandler(connection_params)
    )
    logging.info("Сервер запущен на %s:%d", host, port)
    # Запускаем отдельный поток с нашим циклом событий
    ble_thread = threading.Thread(
        target=start_ble_loop, name="BLELoopThread", daemon=True
    )
    ble_thread.start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Прерывание работы сервера. Завершение...")
    finally:
        # Прежде чем останавливать цикл, вызываем disconnect() для BLE-принтера
        postscript_handler = server.postscript
        if hasattr(postscript_handler, "ble_printer"):
            try:
                # Планируем выполнение disconnect() в цикле событий BLE
                future = asyncio.run_coroutine_threadsafe(
                    postscript_handler.ble_printer.disconnect(), ble_loop
                )
                # Ожидаем завершения задачи
                future.result(
                    timeout=10
                )  # можно указать таймаут для предотвращения бесконечного ожидания
                logging.info("BLE-принтер успешно отключен.")
            except Exception as e:
                logging.error("Ошибка при отключении BLE-принтера: %s", e)

        # Останавливаем сервер и закрываем соединения
        server.shutdown()
        server.server_close()

        # Останавливаем цикл событий BLE и завершаем поток
        ble_loop.call_soon_threadsafe(ble_loop.stop)
        ble_thread.join()


if __name__ == "__main__":
    run_server()
