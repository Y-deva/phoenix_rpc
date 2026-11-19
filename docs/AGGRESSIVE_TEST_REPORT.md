# Агрессивный QA-аудит Phoenix Wallet

Дата: 19.11.2026. Базовая ревизия: 27706e1. Полный набор тестов на момент
проверки: 162 passed. Ниже — 13 подтверждённых дефектов и одно замечание,
найденные дополнительными проверками граничных значений, CSV-экспорта,
QR-виджета, темы и HTTP-клиента.

## Статус исправления

Все 13 дефектов и замечание QA-14 исправлены 19.11.2026. Регрессионные
проверки добавлены в `tests/test_edge_cases.py`; полный набор тестов:
**173 passed**. QA-08 теперь выбрасывает понятную ошибку с текстом о порте
вместо сырого сообщения `urlparse`; это по-прежнему ValueError, потому что
некорректный адрес нельзя молча подменять.

## Сводка

| ID | Важность | Компонент | Симптом |
|----|----------|-----------|---------|
| QA-01 | High | formatting.parse_amount | `1.000,00` превращается в 1 NVC |
| QA-02 | High | formatting.to_decimal/parse_amount | большие суммы вызывают `InvalidOperation` |
| QA-03 | High | validation.validate_amount | Decimal NaN/Infinity вызывает исключение |
| QA-04 | High | table.export_csv | CSV formula injection |
| QA-05 | Medium | rpc.client | HTTP-date в `Retry-After` игнорируется |
| QA-06 | Medium | rpc.client | переполнение после 1024 подряд 429 |
| QA-07 | Medium | validation.base58_decode | нулевой payload декодируется с лишним байтом |
| QA-08 | Low | config.parse_connection | кривой порт даёт сырой ValueError |
| QA-09 | Low | config.parse_connection | IPv6-хост теряет квадратные скобки |
| QA-10 | Low | formatting.format_percent | дробь больше 1 показывается как 1.5% |
| QA-11 | Low | widgets.toast | цвет кнопки закрытия не следует теме |
| QA-12 | Low | widgets.qr | пустой QR сохраняется как успешный PNG |
| QA-13 | Low | formatting.format_amount | параметр `group=False` игнорируется |
| QA-14 | Note | table.export_csv | UTF-8 без BOM, Excel может испортить кириллицу |

## Детали

### QA-01. Смешанные разделители суммы

`phoenix_gui/core/formatting.py:118` при наличии и точки, и запятой всегда
удаляет запятую. Для русской записи с точкой-разделителем тысяч это
масштабная ошибка:

```text
parse_amount("1.000,00") -> Decimal("1.00000000")
parse_amount("1,000.00") -> Decimal("1000.00000000")
```

Пользователь, вставивший сумму из другого приложения, может отправить
1 NVC вместо 1000 NVC. Текущий `AmountField` запрещает второй разделитель
регуляркой, но `parse_amount`/`validate_amount` — публичные функции и
используются вне поля (вставка, импорт, будущие экраны). Исправление:
явно определять десятичный разделитель по позиции/локали, либо отклонять
неоднозначную запись.

### QA-02. Большие конечные суммы роняют парсинг и форматирование

`quantize()` в `to_decimal` (`formatting.py:53`), `format_amount`
(`formatting.py:80`) и `parse_amount` (`formatting.py:134`) не ловит
`decimal.InvalidOperation` для слишком больших конечных чисел:

```text
parse_amount("1e100") -> InvalidOperation
to_decimal("1e100") -> InvalidOperation
format_amount("1e100") -> InvalidOperation
validate_amount("1e100") -> InvalidOperation
```

`AmountField.value()` ловит только `ValueError`, поэтому такой ввод
(например, из API/автозаполнения) даёт необработанное исключение в
Qt-слоте. Нужно ограничить диапазон сумм и обрабатывать `InvalidOperation`
как ошибку валидации.

### QA-03. Decimal NaN/Infinity в validate_amount

Ветка `isinstance(value, Decimal)` обходит `parse_amount` и проверку
`is_finite` (`validation.py:181`). Далее `amount <= 0` и `quantize` падают:

```text
validate_amount(Decimal("NaN")) -> InvalidOperation
validate_amount(Decimal("Infinity")) -> InvalidOperation
```

Ожидается `AmountCheck(valid=False)`, а не исключение. Это важно для
данных из RPC/импорта, где Decimal приходит не только из текстового поля.

### QA-04. CSV formula injection

`SortableTable.export_csv` (`table.py:256-269`) пишет текст ячеек без
экранирования формул. Комментарий транзакции или адрес, начинающийся с
`=`, `+`, `-` или `@`, при открытии CSV в Excel/LibreOffice может быть
воспринят как формула:

```text
A;B
@SUM(A1);x
=1+1;normal
```

Нужно префиксовать такие значения апострофом (или пробелом) при экспорте.

### QA-05. Retry-After в формате HTTP-date игнорируется

`RPCClient.call` (`rpc/client.py:156-168`) читает `Retry-After` только
через `float()`. Стандартный заголовок может быть датой, например
`Wed, 21 Oct 2030 07:28:00 GMT`; тогда клиент берёт экспоненциальную
задержку 2 секунды вместо указанного сервером времени:

```text
RPCRateLimitedError retry_after=2.0
```

Нужно поддерживать оба формата: число секунд и HTTP-date.

### QA-06. Переполнение счётчика 429

В том же блоке `float(2**self._limit_streak)` при длинной серии 429
переполняется:

```text
1024-й подряд ответ 429 -> OverflowError: int too large to convert to float
```

Достаточно ограничить показатель степени до вычисления (`min(streak, 6)`)
и/или использовать сдвиг с насыщением. Это редкий, но реальный сценарий
при сломанном/враждебном прокси.

### QA-07. Base58: лишний нулевой байт

`base58_decode` (`validation.py:78-91`) всегда добавляет ведущие нули к
`decoded`, а для числа 0 `decoded` уже равен `b"\x00"`. В результате
round-trip ломается для payload из нулей:

```text
base58_decode(base58_encode(b"\x00")) -> b"\x00\x00"
```

Адреса с версией 0x08/0x14 не начинаются с нуля, поэтому проверка адресов
не страдает, но helper используется как общий codec и может дать
некорректный payload. Для `number == 0` нужно возвращать только ведущие
нули, без дополнительного `decoded`.

### QA-08. parse_connection: сырой ValueError на порту

`parse_connection("http://127.0.0.1:notaport")` выбрасывает
`ValueError: Port could not be cast to integer value as 'notaport'`
(`config.py:192`). Функция публичная и должна либо возвращать понятную
ошибку, либо подставлять default, а не пропускать исключение urllib.

### QA-09. parse_connection: IPv6 без скобок

```text
parse_connection("http://[::1]:16666")
-> ("http://::1:16666", "", "")
```

Полученный URL синтаксически неверен: при обратном формировании нужно
оборачивать IPv6-хост в `[...]`.

### QA-10. format_percent для дробей больше 1

`format_percent` (`formatting.py:205-213`) умножает на 100 только при
`number <= 1.0`:

```text
format_percent(1.5) -> "1.5%"
format_percent(2.0) -> "2.0%"
```

Если это доля, должно быть 150% и 200%. Текущие вызовы передают 0..1,
поэтому дефект латентный, но контракт функции неоднозначен. Лучше разделить
`format_fraction_percent` и `format_percent_value`.

### QA-11. Кнопка закрытия тоста не следует теме

`Toast.__init__` (`toast.py:102`) жёстко задаёт `#A7B1C2`. Даже если
передать кастомные цвета (все зелёные), пиксели иконки остаются
`(167, 177, 194)`. Это ломает обещанную поддержку светлых/кастомных тем;
`ToastManager.set_colors` обновляет только основную иконку.

### QA-12. Пустой QR сохраняется как успешный PNG

`QrCode.save_png` (`qr.py:55-62`) не проверяет `_matrix` и возвращает
результат `QImage.save`:

```text
QrCode().save_png(path) -> True
```

Файл содержит заглушку "QR-код появится после создания адреса", а
`ReceivePage` сообщает "QR-код сохранен". Сейчас кнопка защищена проверкой
адреса, но при отсутствии `qrcode`/ошибке кодирования это вводит в
заблуждение. Нужно возвращать False, если матрица пуста.

### QA-13. format_amount игнорирует group=False

Параметр `group` (`formatting.py:66-87`) не используется: формат всегда
`{...,.8f}`. Проверка:

```text
format_amount("1234.5", group=False) -> "1,234.50"
```

Ожидается `1234.50`. Параметр либо реализовать, либо удалить, чтобы не
создавать ложный API.

### QA-14. CSV без BOM

`export_csv` пишет UTF-8 без BOM. На Windows Excel часто открывает такой
файл в ANSI и показывает кириллицу как mojibake. Это не ошибка данных,
но заметный UX-дефект для русской локализации; можно добавить `utf-8-sig`
или документировать импорт.

## Проверки

- `QT_QPA_PLATFORM=offscreen pytest -q` — 173 passed после исправлений.
- `ruff format --check` и `ruff check --select E,W,F,E501` — чисто.
- Все сценарии выше покрыты `tests/test_edge_cases.py`; QA-04/QA-14
  дополнительно проверяются через реальный `export_csv`.
