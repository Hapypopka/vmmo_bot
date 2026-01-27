# ============================================
# VMMO Resource History
# ============================================
# Долгосрочное хранение истории ресурсов
# SQLite для графиков за день/неделю/месяц
# ============================================

import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from requests_bot.config import PROFILES_DIR, get_profile_name

# Интервал записи в историю (в секундах)
HISTORY_INTERVAL = 3600  # 1 час


def _get_db_path(profile: str = None) -> str:
    """Возвращает путь к БД истории ресурсов"""
    if not profile:
        profile = get_profile_name()
    if not profile:
        return None
    return os.path.join(PROFILES_DIR, profile, "resource_history.db")


def _get_connection(profile: str = None) -> sqlite3.Connection:
    """Создаёт подключение к БД"""
    db_path = _get_db_path(profile)
    if not db_path:
        return None

    # Создаём директорию если нет
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(profile: str = None):
    """Инициализирует таблицы БД"""
    conn = _get_connection(profile)
    if not conn:
        return

    try:
        cursor = conn.cursor()

        # Таблица истории ресурсов (почасовые снэпшоты)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS resource_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                gold INTEGER DEFAULT 0,
                silver INTEGER DEFAULT 0,
                skulls INTEGER DEFAULT 0,
                minerals INTEGER DEFAULT 0,
                sapphires INTEGER DEFAULT 0,
                rubies INTEGER DEFAULT 0,
                stamps INTEGER DEFAULT 0,
                source TEXT DEFAULT 'auto'
            )
        ''')

        # Индекс по времени
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp
            ON resource_snapshots(timestamp)
        ''')

        # Таблица сессий бота (start/stop события)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bot_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_time TEXT NOT NULL,
                end_time TEXT,
                gold_start INTEGER DEFAULT 0,
                gold_end INTEGER DEFAULT 0,
                silver_start INTEGER DEFAULT 0,
                silver_end INTEGER DEFAULT 0,
                skulls_start INTEGER DEFAULT 0,
                skulls_end INTEGER DEFAULT 0,
                minerals_start INTEGER DEFAULT 0,
                minerals_end INTEGER DEFAULT 0,
                sapphires_start INTEGER DEFAULT 0,
                sapphires_end INTEGER DEFAULT 0,
                rubies_start INTEGER DEFAULT 0,
                rubies_end INTEGER DEFAULT 0,
                stamps_start INTEGER DEFAULT 0,
                stamps_end INTEGER DEFAULT 0
            )
        ''')

        # Таблица изменений между сессиями
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS offline_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_at TEXT NOT NULL,
                prev_session_end TEXT,
                gold_change INTEGER DEFAULT 0,
                silver_change INTEGER DEFAULT 0,
                skulls_change INTEGER DEFAULT 0,
                minerals_change INTEGER DEFAULT 0,
                sapphires_change INTEGER DEFAULT 0,
                rubies_change INTEGER DEFAULT 0,
                stamps_change INTEGER DEFAULT 0
            )
        ''')

        conn.commit()
    finally:
        conn.close()


def _resources_to_db_columns(resources: Dict) -> Dict:
    """Конвертирует русские названия в колонки БД"""
    mapping = {
        'золото': 'gold',
        'серебро': 'silver',
        'черепа': 'skulls',
        'минералы': 'minerals',
        'сапфиры': 'sapphires',
        'рубины': 'rubies',
        'марки': 'stamps',
    }

    result = {}
    for rus, eng in mapping.items():
        result[eng] = resources.get(rus, 0)
    return result


def _db_columns_to_resources(row: sqlite3.Row) -> Dict:
    """Конвертирует колонки БД в русские названия"""
    mapping = {
        'gold': 'золото',
        'silver': 'серебро',
        'skulls': 'черепа',
        'minerals': 'минералы',
        'sapphires': 'сапфиры',
        'rubies': 'рубины',
        'stamps': 'марки',
    }

    result = {}
    for eng, rus in mapping.items():
        val = row[eng] if eng in row.keys() else 0
        if val:
            result[rus] = val
    return result


# ═══════════════════════════════════════════════════════════════════
# SNAPSHOT FUNCTIONS (почасовая история)
# ═══════════════════════════════════════════════════════════════════

def save_snapshot(resources: Dict, source: str = 'auto', profile: str = None):
    """
    Сохраняет снэпшот ресурсов в историю.

    Args:
        resources: dict с ресурсами (русские названия)
        source: источник ('auto', 'start', 'stop', 'manual')
        profile: имя профиля (опционально)
    """
    if not resources:
        return

    init_db(profile)
    conn = _get_connection(profile)
    if not conn:
        return

    try:
        cursor = conn.cursor()
        db_res = _resources_to_db_columns(resources)

        cursor.execute('''
            INSERT INTO resource_snapshots
            (timestamp, gold, silver, skulls, minerals, sapphires, rubies, stamps, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            db_res['gold'], db_res['silver'], db_res['skulls'],
            db_res['minerals'], db_res['sapphires'], db_res['rubies'],
            db_res['stamps'], source
        ))

        conn.commit()
    finally:
        conn.close()


def get_last_snapshot(profile: str = None) -> Optional[Dict]:
    """Возвращает последний снэпшот"""
    conn = _get_connection(profile)
    if not conn:
        return None

    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM resource_snapshots
            ORDER BY timestamp DESC LIMIT 1
        ''')
        row = cursor.fetchone()
        if row:
            return {
                'timestamp': row['timestamp'],
                'resources': _db_columns_to_resources(row),
                'source': row['source']
            }
        return None
    finally:
        conn.close()


def should_save_snapshot(profile: str = None) -> bool:
    """Проверяет, нужно ли сохранять новый снэпшот (раз в час)"""
    last = get_last_snapshot(profile)
    if not last:
        return True

    try:
        last_time = datetime.fromisoformat(last['timestamp'])
        return (datetime.now() - last_time).total_seconds() >= HISTORY_INTERVAL
    except Exception:
        return True


def get_history(hours: int = 24, profile: str = None) -> List[Dict]:
    """
    Получает историю снэпшотов за указанный период.

    Args:
        hours: сколько часов назад (24 = день, 168 = неделя, 720 = месяц)
        profile: имя профиля

    Returns:
        list: [{'timestamp': ..., 'resources': {...}}, ...]
    """
    conn = _get_connection(profile)
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        since = (datetime.now() - timedelta(hours=hours)).isoformat()

        cursor.execute('''
            SELECT * FROM resource_snapshots
            WHERE timestamp >= ?
            ORDER BY timestamp ASC
        ''', (since,))

        result = []
        for row in cursor.fetchall():
            result.append({
                'timestamp': row['timestamp'],
                'resources': _db_columns_to_resources(row),
                'source': row['source']
            })
        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# SESSION TRACKING (старт/стоп бота)
# ═══════════════════════════════════════════════════════════════════

def start_bot_session(resources: Dict, profile: str = None) -> Tuple[int, Optional[Dict]]:
    """
    Регистрирует старт сессии бота.
    Сравнивает с последней сессией и вычисляет offline изменения.

    Args:
        resources: текущие ресурсы при старте
        profile: имя профиля

    Returns:
        tuple: (session_id, offline_changes или None)
    """
    if not resources:
        return None, None

    init_db(profile)
    conn = _get_connection(profile)
    if not conn:
        return None, None

    try:
        cursor = conn.cursor()
        db_res = _resources_to_db_columns(resources)

        # Получаем последнюю завершённую сессию
        cursor.execute('''
            SELECT * FROM bot_sessions
            WHERE end_time IS NOT NULL
            ORDER BY end_time DESC LIMIT 1
        ''')
        last_session = cursor.fetchone()

        offline_changes = None

        # Сравниваем с концом прошлой сессии
        if last_session:
            changes = {
                'золото': db_res['gold'] - (last_session['gold_end'] or 0),
                'серебро': db_res['silver'] - (last_session['silver_end'] or 0),
                'черепа': db_res['skulls'] - (last_session['skulls_end'] or 0),
                'минералы': db_res['minerals'] - (last_session['minerals_end'] or 0),
                'сапфиры': db_res['sapphires'] - (last_session['sapphires_end'] or 0),
                'рубины': db_res['rubies'] - (last_session['rubies_end'] or 0),
                'марки': db_res['stamps'] - (last_session['stamps_end'] or 0),
            }

            # Убираем нули
            changes = {k: v for k, v in changes.items() if v != 0}

            if changes:
                offline_changes = {
                    'prev_session_end': last_session['end_time'],
                    'changes': changes
                }

                # Сохраняем в таблицу offline_changes
                cursor.execute('''
                    INSERT INTO offline_changes
                    (detected_at, prev_session_end, gold_change, silver_change,
                     skulls_change, minerals_change, sapphires_change, rubies_change, stamps_change)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    datetime.now().isoformat(),
                    last_session['end_time'],
                    changes.get('золото', 0),
                    changes.get('серебро', 0),
                    changes.get('черепа', 0),
                    changes.get('минералы', 0),
                    changes.get('сапфиры', 0),
                    changes.get('рубины', 0),
                    changes.get('марки', 0),
                ))

        # Создаём новую сессию
        cursor.execute('''
            INSERT INTO bot_sessions
            (start_time, gold_start, silver_start, skulls_start,
             minerals_start, sapphires_start, rubies_start, stamps_start)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            db_res['gold'], db_res['silver'], db_res['skulls'],
            db_res['minerals'], db_res['sapphires'], db_res['rubies'],
            db_res['stamps']
        ))

        session_id = cursor.lastrowid
        conn.commit()

        # Сохраняем снэпшот с пометкой 'start'
        save_snapshot(resources, 'start', profile)

        return session_id, offline_changes
    finally:
        conn.close()


def end_bot_session(resources: Dict, session_id: int = None, profile: str = None):
    """
    Регистрирует конец сессии бота.

    Args:
        resources: ресурсы на момент остановки
        session_id: ID сессии (если None - берёт последнюю незавершённую)
        profile: имя профиля
    """
    if not resources:
        return

    conn = _get_connection(profile)
    if not conn:
        return

    try:
        cursor = conn.cursor()
        db_res = _resources_to_db_columns(resources)

        # Если session_id не указан - берём последнюю незавершённую
        if session_id is None:
            cursor.execute('''
                SELECT id FROM bot_sessions
                WHERE end_time IS NULL
                ORDER BY start_time DESC LIMIT 1
            ''')
            row = cursor.fetchone()
            if row:
                session_id = row['id']

        if session_id:
            cursor.execute('''
                UPDATE bot_sessions SET
                    end_time = ?,
                    gold_end = ?,
                    silver_end = ?,
                    skulls_end = ?,
                    minerals_end = ?,
                    sapphires_end = ?,
                    rubies_end = ?,
                    stamps_end = ?
                WHERE id = ?
            ''', (
                datetime.now().isoformat(),
                db_res['gold'], db_res['silver'], db_res['skulls'],
                db_res['minerals'], db_res['sapphires'], db_res['rubies'],
                db_res['stamps'],
                session_id
            ))
            conn.commit()

        # Сохраняем снэпшот с пометкой 'stop'
        save_snapshot(resources, 'stop', profile)
    finally:
        conn.close()


def get_sessions(limit: int = 10, profile: str = None) -> List[Dict]:
    """
    Получает последние сессии бота.

    Returns:
        list: [{'start_time': ..., 'end_time': ..., 'earned': {...}}, ...]
    """
    conn = _get_connection(profile)
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM bot_sessions
            WHERE end_time IS NOT NULL
            ORDER BY end_time DESC LIMIT ?
        ''', (limit,))

        result = []
        for row in cursor.fetchall():
            earned = {
                'золото': (row['gold_end'] or 0) - (row['gold_start'] or 0),
                'серебро': (row['silver_end'] or 0) - (row['silver_start'] or 0),
                'черепа': (row['skulls_end'] or 0) - (row['skulls_start'] or 0),
                'минералы': (row['minerals_end'] or 0) - (row['minerals_start'] or 0),
                'сапфиры': (row['sapphires_end'] or 0) - (row['sapphires_start'] or 0),
                'рубины': (row['rubies_end'] or 0) - (row['rubies_start'] or 0),
                'марки': (row['stamps_end'] or 0) - (row['stamps_start'] or 0),
            }
            # Убираем нули
            earned = {k: v for k, v in earned.items() if v != 0}

            # Длительность
            try:
                start = datetime.fromisoformat(row['start_time'])
                end = datetime.fromisoformat(row['end_time'])
                duration_hours = round((end - start).total_seconds() / 3600, 1)
            except Exception:
                duration_hours = 0

            result.append({
                'start_time': row['start_time'],
                'end_time': row['end_time'],
                'duration_hours': duration_hours,
                'earned': earned
            })

        return result
    finally:
        conn.close()


def get_offline_changes(limit: int = 10, profile: str = None) -> List[Dict]:
    """
    Получает историю изменений между сессиями (offline).

    Returns:
        list: [{'detected_at': ..., 'changes': {...}}, ...]
    """
    conn = _get_connection(profile)
    if not conn:
        return []

    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM offline_changes
            ORDER BY detected_at DESC LIMIT ?
        ''', (limit,))

        result = []
        for row in cursor.fetchall():
            changes = {
                'золото': row['gold_change'],
                'серебро': row['silver_change'],
                'черепа': row['skulls_change'],
                'минералы': row['minerals_change'],
                'сапфиры': row['sapphires_change'],
                'рубины': row['rubies_change'],
                'марки': row['stamps_change'],
            }
            # Убираем нули
            changes = {k: v for k, v in changes.items() if v != 0}

            result.append({
                'detected_at': row['detected_at'],
                'prev_session_end': row['prev_session_end'],
                'changes': changes
            })

        return result
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# AGGREGATION (для графиков)
# ═══════════════════════════════════════════════════════════════════

def get_chart_data(resource: str, period: str = 'day', profile: str = None) -> Dict:
    """
    Получает данные для графика конкретного ресурса.

    Args:
        resource: 'gold', 'skulls', 'minerals', etc.
        period: 'day' (24h), 'week' (7d), 'month' (30d)
        profile: имя профиля

    Returns:
        dict: {'labels': [...], 'values': [...], 'min': N, 'max': N}
    """
    hours_map = {
        'day': 24,
        'week': 168,
        'month': 720
    }
    hours = hours_map.get(period, 24)

    history = get_history(hours, profile)

    if not history:
        return {'labels': [], 'values': [], 'min': 0, 'max': 0}

    # Маппинг английских в русские
    eng_to_rus = {
        'gold': 'золото',
        'silver': 'серебро',
        'skulls': 'черепа',
        'minerals': 'минералы',
        'sapphires': 'сапфиры',
        'rubies': 'рубины',
        'stamps': 'марки',
    }

    rus_name = eng_to_rus.get(resource, resource)

    labels = []
    values = []

    for snapshot in history:
        try:
            dt = datetime.fromisoformat(snapshot['timestamp'])
            if period == 'day':
                label = dt.strftime('%H:%M')
            elif period == 'week':
                label = dt.strftime('%a %H:%M')
            else:
                label = dt.strftime('%d.%m')

            labels.append(label)
            values.append(snapshot['resources'].get(rus_name, 0))
        except Exception:
            continue

    return {
        'labels': labels,
        'values': values,
        'min': min(values) if values else 0,
        'max': max(values) if values else 0
    }


def get_all_chart_data(period: str = 'day', profile: str = None) -> Dict:
    """
    Получает данные для всех ресурсов.

    Returns:
        dict: {
            'labels': [...],
            'datasets': {
                'gold': [...],
                'skulls': [...],
                ...
            }
        }
    """
    hours_map = {
        'day': 24,
        'week': 168,
        'month': 720
    }
    hours = hours_map.get(period, 24)

    history = get_history(hours, profile)

    if not history:
        return {'labels': [], 'datasets': {}}

    labels = []
    datasets = {
        'gold': [],
        'silver': [],
        'skulls': [],
        'minerals': [],
        'sapphires': [],
        'rubies': [],
    }

    eng_to_rus = {
        'gold': 'золото',
        'silver': 'серебро',
        'skulls': 'черепа',
        'minerals': 'минералы',
        'sapphires': 'сапфиры',
        'rubies': 'рубины',
    }

    for snapshot in history:
        try:
            dt = datetime.fromisoformat(snapshot['timestamp'])
            if period == 'day':
                label = dt.strftime('%H:%M')
            elif period == 'week':
                label = dt.strftime('%a %H:%M')
            else:
                label = dt.strftime('%d.%m')

            labels.append(label)

            for eng, rus in eng_to_rus.items():
                datasets[eng].append(snapshot['resources'].get(rus, 0))
        except Exception:
            continue

    return {
        'labels': labels,
        'datasets': datasets
    }


# ═══════════════════════════════════════════════════════════════════
# CLEANUP
# ═══════════════════════════════════════════════════════════════════

def cleanup_old_data(days: int = 90, profile: str = None):
    """Удаляет данные старше указанного количества дней"""
    conn = _get_connection(profile)
    if not conn:
        return

    try:
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        cursor.execute('DELETE FROM resource_snapshots WHERE timestamp < ?', (cutoff,))
        cursor.execute('DELETE FROM bot_sessions WHERE end_time < ?', (cutoff,))
        cursor.execute('DELETE FROM offline_changes WHERE detected_at < ?', (cutoff,))

        conn.commit()

        # Оптимизация БД
        cursor.execute('VACUUM')
    finally:
        conn.close()
