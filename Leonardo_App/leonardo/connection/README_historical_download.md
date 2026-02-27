Leonardo — Historical Download Subsystem (Partial README)

Date: 02/26/2026
Scope: Connection + Historical Data Layer (partial implementation)
Status: Functional, stable, extensible

1. Purpose of This Document

This README documents the historical data download subsystem implemented as of 02/26/2026.

It covers:

Folder structure

Core orchestration

Exchange adapter responsibilities

Pagination model

Candle integrity rules

Audit integration

Current limitations

Dependency diagram

This is a partial README, focused only on the connection and historical data ingestion layer.
GUI and Core documentation will be updated after the historical chart window is completed.

2. Historical Storage Architecture

Historical data is stored using a partitioned directory model to avoid oversized folders and to support scalable growth.

Folder Structure
data/
└── historical/
    └── {exchange}/
        └── {market_type}/
            └── {symbol}/
                └── {timeframe}/
                    ├── ohlcv/
                    │   └── candles.csv
                    ├── indicators/
                    ├── oscillators/
                    ├── trade_signal/
                    └── signal_elaboration/
Design Rationale

Prevent flat large directories.

Allow independent timeframe storage.

Prepare for computed artifacts (indicators, signals).

Keep raw OHLCV data isolated.

Enable fast lookup and deterministic paths.

Currently active:

ohlcv/candles.csv

The remaining folders are pre-architected for future modules.

3. Core Historical Downloader

File:

leonardo/data/historical/downloader.py
Responsibility

The HistoricalDownloader orchestrates:

Input canonicalization

Path resolution

Exchange paging

Idempotent merge

Atomic persistence

Audit emission

Background task execution

3.1 Paging Strategy (Backward Cursor Model)

Bybit’s kline endpoint works as a sliding window.
To download full history correctly, we use backward pagination:

Initial end_cursor_ms = server_time (or user-provided end_ms)

Loop:
    fetch batch with end_ms = end_cursor_ms
    merge + persist
    end_cursor_ms = oldest_ts - 1

This continues until:

No batch returned

Cursor stops moving (guard)

Start bound reached

max_pages limit reached

This prevents the “only 500 candles downloaded” issue.

3.2 Infinite Loop Guards

Two safeguards:

End cursor must strictly decrease:

end_cursor_ms < last_end_cursor

max_pages safety cap:

max_pages = 10_000

Prevents runaway loops.

3.3 Last Candle Handling (Critical Logic)

Exchanges return the currently forming candle.

We drop the last candle only if:

start_ms is None

end_ms is None

Initial page derived from server time

Why?

Because:

The last bar is still forming.

It contains incomplete OHLC values.

But if user specifies a date range, we must respect the range.

This ensures data integrity without corrupting user-defined downloads.

3.4 Server Time Synchronization

Downloader prefers exchange server time:

GET /v5/market/time

Fallback:

time.time() * 1000

This avoids:

Timezone mismatches

Local clock drift

Partial candle misclassification

4. Exchange Adapter — Bybit

File:

leonardo/connection/exchange/adapters/bybit.py
Responsibilities

REST historical OHLCV

Websocket streaming

Server time endpoint

Timeframe normalization

Market validation

4.1 Historical Endpoint Used
GET /v5/market/kline

Parameters:

category (spot, linear, inverse, option)

interval

start

end

limit (clamped 1–1000)

4.2 Candle Conversion

Returned data:

[startTime, open, high, low, close, volume, turnover]

Converted to internal:

Candle(ts_ms, open, high, low, close, volume, is_closed)

Sorted ascending.

4.3 Forming Candle Detection

Using:

server_time_ms
timeframe_duration_ms

If:

ts_ms + duration > server_time

Then:

is_closed = False

This allows downloader to safely remove the live bar when appropriate.

5. CSV Storage Layer

File:

leonardo/data/historical/store_csv.py
Responsibilities

Read candles

Atomic write

Idempotent merge

Guarantees

No duplicates (merge by ts_ms)

Sorted output

Safe overwrite

6. Naming Layer

File:

leonardo/data/naming.py

Ensures:

Canonical exchange names

Canonical market types

Normalized symbols

Canonical timeframe strings

Prevents:

Silent mismatches

Dirty inputs reaching adapter layer

7. GUI — Historical Download Window

File:

leonardo/gui/historical_download_window.py
Responsibilities

Collect user input

Validate canonical data

Submit background job

Poll audit events

Display progress

Prevent invalid execution

7.1 Market Type Enforcement

Market dropdown now starts blank:

["", "spot", "linear", "inverse", "options"]

If user presses Start without selecting:

Market type not selected

Prevents silent wrong-market downloads.

7.2 Async Safety

Core context captured on GUI thread.

Background job submitted via CoreBridge.submit.

GUI updates performed via polling timer.

No cross-thread QObject mutation.

Fixes:

QObject::killTimer freeze

Thread ownership violations

8. Audit Integration

All lifecycle events emit:

event_type = "historical_download"

Events:

download started

download progress

download completed

download failed

GUI polls via:

CoreBridge.try_get_audit_snapshot()

This decouples GUI and Core.

9. Dependency Diagram
GUI (HistoricalDownloadWindow)
        │
        ▼
CoreBridge
        │
        ▼
HistoricalDownloader
        │
        ▼
BybitExchange (REST adapter)
        │
        ▼
GET /v5/market/kline
        │
        ▼
CsvOHLCVStore
        │
        ▼
data/historical/{...}/ohlcv/candles.csv

Parallel:

HistoricalDownloader
        │
        ▼
ctx.audit.emit(...)
        │
        ▼
GUI polling via CoreBridge
10. Problems Solved
Issue	Resolution
Only 500 candles downloaded	Removed premature page break
Last candle incorrect	Conditional drop logic
Timezone inconsistencies	Exchange server time
GUI freeze	Proper async submission model
Silent wrong market type	Forced explicit selection
Infinite loop risk	Cursor movement guard
Duplicate candles	Idempotent merge
11. Current System State (02/26/2026)

The subsystem now:

Downloads full historical data correctly.

Handles pagination deterministically.

Avoids partial candle corruption.

Stores partitioned CSV datasets.

Is async-safe and GUI-safe.

Is extensible to additional exchanges.

12. Not Yet Implemented

Exchange registry abstraction (currently Bybit hardcoded)

Historical chart rendering window

Download cancellation logic

Automatic incremental sync mode

Multi-exchange support

Data integrity validation layer

13. Architectural Summary

This implementation moves Leonardo from:

Prototype that fetches limited candles

to

Deterministic historical ingestion subsystem with integrity guarantees

The foundation for:

Backtesting

Indicator calculation

Simulation engine

Historical chart rendering

is now in place.

End of Partial README — 02/26/2026