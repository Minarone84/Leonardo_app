import inspect
from leonardo.connection.exchange.adapters.bybit import BybitExchange

print("isabstract:", inspect.isabstract(BybitExchange))
print("has fetch_ohlcv:", hasattr(BybitExchange, "fetch_ohlcv"))
print("has stream_ohlcv:", hasattr(BybitExchange, "stream_ohlcv"))