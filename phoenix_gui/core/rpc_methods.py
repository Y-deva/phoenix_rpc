"""Catalogue of daemon RPC methods exposed by the console."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RpcMethod:
    """One console command with a short help string."""

    name: str
    params: str
    description: str
    danger: bool = False

    @property
    def signature(self) -> str:
        """Return a readable command signature."""
        return f"{self.name} {self.params}".strip()


METHODS: tuple[RpcMethod, ...] = (
    RpcMethod("getinfo", "", "Общее состояние демона: версия, блоки, соединения."),
    RpcMethod("getblockcount", "", "Текущая высота цепочки."),
    RpcMethod("getblockhash", "<height>", "Хеш блока по его высоте."),
    RpcMethod("getblock", "<hash> [verbosity]", "Данные блока по хешу."),
    RpcMethod(
        "getrawtransaction", "<txid> [verbose]", "Сырая транзакция по идентификатору."
    ),
    RpcMethod(
        "getbalance", "[account] [minconf]", "Баланс с учетом неподтвержденных входов."
    ),
    RpcMethod(
        "getnewaddress",
        "[account]",
        "Новый P2SH-адрес кошелька.",
    ),
    RpcMethod(
        "listtransactions", "[account] [count] [offset]", "История операций кошелька."
    ),
    RpcMethod(
        "listunspent",
        "[minconf] [maxconf] [addresses]",
        "Неизрасходованные выходы с фильтрами.",
    ),
    RpcMethod(
        "sendtoaddress",
        "<address> <amount> [comment]",
        "Отправка средств через прокси. Комментарий попадает в OP_RETURN.",
        danger=True,
    ),
    RpcMethod(
        "signrawtransaction",
        "<hex>",
        "Подпись входов P2SH-Falcon через прокси.",
    ),
    RpcMethod(
        "sendrawtransaction",
        "<hex>",
        "Публикация подписанной транзакции в сеть.",
        danger=True,
    ),
    RpcMethod(
        "createrawtransaction",
        "<inputs> <outputs> [data]",
        "Сборка сырой транзакции для ручного контроля входов.",
    ),
    RpcMethod("decoderawtransaction", "<hex>", "Разбор сырой транзакции."),
    RpcMethod("validateaddress", "<address>", "Проверка адреса и его типа."),
    RpcMethod("getaddressesbyaccount", "[account]", "Адреса, привязанные к аккаунту."),
    RpcMethod("listaccounts", "[minconf]", "Список аккаунтов и их балансов."),
    RpcMethod("getpeerinfo", "", "Подключенные узлы сети."),
    RpcMethod("getconnectioncount", "", "Количество активных соединений."),
    RpcMethod("getmininginfo", "", "Параметры майнинга и сложность."),
    RpcMethod("getdifficulty", "", "Текущая сложность сети."),
    RpcMethod("getnetworkhashps", "[blocks] [height]", "Оценка хешрейта сети."),
    RpcMethod("getwork", "[data]", "Работа для внешнего майнера."),
    RpcMethod("help", "[command]", "Справка демона по команде."),
    RpcMethod("settxfee", "<amount>", "Базовая комиссия за килобайт.", danger=True),
    RpcMethod(
        "walletpassphrase",
        "<passphrase> <timeout>",
        "Разблокировать кошелек.",
        danger=True,
    ),
    RpcMethod("walletlock", "", "Заблокировать кошелек."),
    RpcMethod("stop", "", "Остановить демон novacoind.", danger=True),
)

METHOD_MAP = {method.name: method for method in METHODS}
NAMES = tuple(method.name for method in METHODS)


def find_method(name: str) -> RpcMethod | None:
    """Return a catalog entry by name, case-insensitively."""
    return METHOD_MAP.get((name or "").strip().lower())


def method_names() -> tuple[str, ...]:
    """Return all known method names in catalog order."""
    return NAMES
