# Catcombo

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python Version](https://img.shields.io/badge/Python-3.7%2B-blue.svg)
![Status](https://img.shields.io/badge/status-active-brightgreen.svg)

![Логотип](media/catcombo_logo.png)

## О проекте

Этот проект разработан специально для термопринтера LX-D02, который был приобретён на Ozon примерно за 600₽. LX-D02 — компактный термопринтер с разрешением 200×200 точек, идеально подходящий для печати чеков, этикеток и небольших изображений. Он особенно полезен для печати штрих-кодов и QR-кодов на маркетплейсах, являясь бюджетным решением для малого бизнеса.

Проект реализует сервер IPP (Internet Printing Protocol) для управления печатью на этом принтере с использованием Bluetooth Low Energy (BLE). Основные возможности включают:

- Асинхронную обработку BLE-соединения для эффективной и надежной передачи данных на принтер.
- Поддержку PostScript для подготовки печатного контента и обработки изображений, оптимизированных для термопринтера.
- Управление параметрами печати, такими как уровень черного, позволяющее настроить качество печати в зависимости от требований.

Благодаря этой разработке, даже недорогой термопринтер LX-D02 может быть эффективно интегрирован в современные печатные решения, обеспечивая быстрый и стабильный выход печатных материалов для различных задач, включая бюджетную печать кодов на маркетплейсах.


**Python BLE IPP Printer Server** — легковесный асинхронный сервер IPP для управления Bluetooth Low Energy термопринтерами. Проект позволяет отправлять печатные задания через сеть к BLE-принтеру с использованием протокола IPP и обработки PostScript изображений.

## 🚀 Особенности

- 🧵 **Асинхронный сервер**: Обработка нескольких запросов одновременно с использованием `asyncio`.
- 📡 **Поддержка BLE**: Интеграция с Bluetooth Low Energy принтерами через библиотеку `bleak`.
- 🖨️ **Обработка PostScript**: Поддержка многостраничных документов, обрезка краёв и подготовка изображений для печати с помощью `Wand`.
- 📄 **PPD поддержка**: Чтение и предоставление PPD файлов для конфигурации принтера.
- 🔧 **Легкая настройка**: Параметры подключения и качества печати задаются через аргументы командной строки.

## ⚙️ Быстрый старт

1. **Клонируйте репозиторий и перейдите в его директорию:**

    ```bash
    git clone https://github.com/big-vl/catcombo.git
    cd catcombo
    ```

2. **Создайте виртуальное окружение и установите зависимости:**

    ```bash
    python3 -m venv venv
    source venv/bin/activate   # На Windows: venv\Scripts\activate
    pip install -r requirements.txt
    ```

3. **Запустите тестовую печать**

    ```bash
    python main.py --file media/test1.png --black_level 5 --name "LX-D02"
    ```

### Развернутая инструкция
Аргументы командной строки
--file или -f (обязательный):
Путь к файлу изображения, которое необходимо отправить на печать.
`Пример: --file image.png`

--address или -a (необязательный):
MAC-адрес Bluetooth-принтера. Если не указан, будет выполнен поиск устройства по имени.
`Пример: --address 00:11:22:33:44:55`

--black_level или -b (необязательный, по умолчанию 7):
Уровень черного цвета для принтера (от 0 до 7). Определяет насыщенность черного при печати.
`Пример: --black_level 5`

--name или -n (необязательный, по умолчанию "LX-D02"):
Имя Bluetooth-устройства для поиска, если MAC-адрес не указан.
`Пример: --name "LX-D02"`

### Пример работы программы
Поиск устройства:
Если не указан MAC-адрес (--address), скрипт попытается найти принтер по имени, указанному в --name.

### Инициализация и подключение:
Скрипт устанавливает соединение с принтером, инициализирует его и устанавливает необходимые параметры перед печатью.

### Печать изображения:
После успешного подключения и инициализации скрипт отправляет указанное изображение на печать.

### Завершение работы:
После печати скрипт отключается от принтера, освобождая ресурсы.

## IPP Server на основе Python

IPP (Internet Printing Protocol) сервер, реализованный с использованием Python и модуля `socketserver`. Сервер обрабатывает HTTP/IPP запросы, взаимодействует с PostScript-принтером и предоставляет PPD файлы по запросу.

### Особенности
- Поддержка HTTP GET и POST запросов для взаимодействия с сервером.
- Обработка IPP запросов и взаимодействие с PostScript-принтером.
- Возможность выдачи PPD файлов по HTTP GET запросу.
- Многопоточный сервер для одновременной обработки нескольких запросов.
- Логирование событий для отслеживания работы сервера.

### Зависимости

- Python 3.6 и выше
- Стандартные библиотеки: `io`, `struct`, `logging`, `socketserver`, `http.server`
- Дополнительные зависимости:
  - bleak для соеденения по Bluetooth
  - wand для обработки изображения
  - Pillow для обработки изображения

### Установка

1. Клонируйте репозиторий или скопируйте файлы проекта на вашу машину.
2. Убедитесь, что у вас установлен Python версии 3.7 или выше.
3. Установите необходимые зависимости, они требуются модулям.

### Запуск сервера

Для запуска сервера выполните:

```bash
python main.py
```

После запуска сервер начнет прослушивание на 0.0.0.0:6310 по умолчанию.
В консоли будет отображаться сообщение:

```bash
INFO:root:Сервер запущен на 0.0.0.0:6310
```

### Использование
Проверка работы IPP сервера:

Откройте браузер и перейдите по адресу http://localhost:6310/. Вы должны увидеть сообщение "IPP server is running ...".
Получение PPD файла:

Перейдите по URL, оканчивающемуся на .ppd (например, http://localhost:6310/LX-D2-thermal_57mm_203dpi.ppd), чтобы получить содержимое PPD файла.

### Добавление принтера в систему по протоколу IPP
Чтобы использовать сервер для печати в вашей операционной системе, добавьте принтер через IPP:

1. **Получите URL принтера:**  
   Основной URL для подключения к принтеру обычно имеет вид:  
   ipp://localhost:6310
   Убедитесь, что используете правильный порт и путь, соответствующие вашему серверу.

2. **Добавление принтера в Windows:**
   - Откройте «Настройки» → «Устройства» → «Принтеры и сканеры».
   - Выберите «Добавить принтер» → «Не указан нужный принтер» → «Добавить принтер по IP-адресу или имени хоста».
   - Выберите «Протокол IPP» и введите URL принтера (например, ipp://localhost:6310).
   - Следуйте инструкциям мастера, при необходимости укажите PPD файл, скачанный ранее.

3. **Добавление принтера в macOS:**
   - Откройте «Системные настройки» → «Принтеры и сканеры».
   - Нажмите на значок «+», чтобы добавить новый принтер.
   - Выберите вкладку «IP» и введите URL принтера в поле «Адрес», выберите протокол IPP.
   - Укажите PPD-файл, если система не определит его автоматически.
   - Нажмите «Добавить».

4. **Добавление принтера в Linux:**
   - Откройте настройки принтеров (например, через веб-интерфейс CUPS: http://localhost:631/).
   - Выберите «Добавить принтер» и в качестве типа подключения укажите «Интернет-протокол печати (IPP)».
   - Введите URL принтера (например, ipp://localhost:6310).
   - Когда будет предложено, выберите PPD файл для модели LX-D2 или используйте предоставленный в проекте.
   - Сохраните настройки.

После добавления принтера вы сможете отправлять печатные задания через систему, используя установленный IPP-принтер.

## Обоснование выбора архитектуры

**Почему основная серверная часть выглядит синхронно**
Синхронный HTTP/IPP сервер: Классы IPPRequestHandler и IPPServer основаны на синхронной модели обработки запросов. Они обрабатывают каждый запрос в отдельном потоке благодаря ThreadingTCPServer. Это значит, что внутри каждого такого потока выполнение может блокироваться при I/O операциях.

Комбинированный подход: Вместо того чтобы переписывать весь сервер на асинхронную модель (что потребовало бы существенных изменений, особенно в части HTTP/IPP обработки), асинхронность внедряется целенаправленно для операций, связанных с BLE-принтером. Таким образом, сервер может продолжать обработку новых запросов в отдельных потоках, а отдельные блокирующие вызовы, связанные с BLE, выполняются асинхронно в выделенном цикле событий.

**Преимущества такого подхода**
1. Изоляция асинхронности: Асинхронные BLE операции отделены от основной логики сервера, что упрощает интеграцию с существующим синхронным кодом.
2. Неблокирующие BLE задачи: Отправка на печать и управление Bluetooth-соединением выполняются без блокировки потоков, в которых запущен HTTP/IPP сервер.
3. Управление ресурсами: Использование отдельного цикла событий для BLE позволяет эффективно распределять ресурсы и выполнять длительные операции параллельно с обработкой новых HTTP запросов.
Таким образом, несмотря на то что основная часть сервера выглядит синхронной, асинхронность активно применяется для операций с Bluetooth-принтером, обеспечивая более эффективное и отзывчивое взаимодействие в этих узких местах.
