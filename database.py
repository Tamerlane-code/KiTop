"""
Varaq bot — ma'lumotlar bazasi qismi.
SQLite ishlatiladi — kichik loyihalar uchun eng oddiy va arzon yechim.
Foydalanuvchi soni ko'paysa, shu fayldagi funksiyalarni o'zgartirmasdan
PostgreSQL'ga o'tish mumkin bo'ladi.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "varaq.db"


@contextmanager
def get_connection():
    """Har bir so'rov uchun xavfsiz ulanish ochadi va avtomatik yopadi."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Bot birinchi marta ishga tushganda kerakli jadvallarni yaratadi."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                nickname TEXT NOT NULL,
                region TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                region TEXT NOT NULL,
                listing_type TEXT NOT NULL CHECK(listing_type IN ('rent', 'sale')),
                price INTEGER NOT NULL,
                market_price INTEGER,
                condition TEXT,
                note TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (owner_id) REFERENCES users(telegram_id)
            )
        """)


def upsert_user(telegram_id: int, nickname: str, region: str | None = None):
    """Foydalanuvchini qo'shadi yoki mavjud bo'lsa ma'lumotini yangilaydi."""
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        if existing:
            if region:
                conn.execute(
                    "UPDATE users SET nickname = ?, region = ? WHERE telegram_id = ?",
                    (nickname, region, telegram_id),
                )
            else:
                conn.execute(
                    "UPDATE users SET nickname = ? WHERE telegram_id = ?",
                    (nickname, telegram_id),
                )
        else:
            conn.execute(
                "INSERT INTO users (telegram_id, nickname, region, created_at) VALUES (?, ?, ?, ?)",
                (telegram_id, nickname, region, datetime.now().isoformat()),
            )


def get_user(telegram_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def add_book(owner_id: int, title: str, author: str, region: str,
             listing_type: str, price: int, market_price: int | None,
             condition: str, note: str = ""):
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO books
               (owner_id, title, author, region, listing_type, price, market_price, condition, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (owner_id, title, author, region, listing_type, price,
             market_price, condition, note, datetime.now().isoformat()),
        )
        return cursor.lastrowid


def search_books(query: str = "", region: str | None = None, listing_type: str | None = None,
                  user_region: str | None = None, sort_asc: bool = True):
    """
    Kitoblarni qidiradi.
    Geo-priority mantiqi: foydalanuvchi hududidagi e'lonlar avval ko'rsatiladi,
    har bir guruh ichida esa narx bo'yicha (arzondan qimmatga yoki aksincha) saralanadi.
    """
    sql = """SELECT books.*, users.nickname AS owner_nickname
              FROM books JOIN users ON books.owner_id = users.telegram_id
              WHERE books.is_active = 1"""
    params = []

    if query:
        sql += " AND (books.title LIKE ? OR books.author LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if region:
        sql += " AND books.region = ?"
        params.append(region)
    if listing_type:
        sql += " AND books.listing_type = ?"
        params.append(listing_type)

    with get_connection() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    for r in rows:
        r["_is_local"] = 0 if (user_region and r["region"] == user_region) else 1

    rows.sort(key=lambda r: (r["_is_local"], r["price"] if sort_asc else -r["price"]))
    return rows


def get_book(book_id: int):
    with get_connection() as conn:
        row = conn.execute(
            """SELECT books.*, users.nickname AS owner_nickname, users.telegram_id AS owner_telegram_id
               FROM books JOIN users ON books.owner_id = users.telegram_id
               WHERE books.id = ?""",
            (book_id,),
        ).fetchone()
        return dict(row) if row else None


def get_user_books(owner_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM books WHERE owner_id = ? AND is_active = 1 ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def deactivate_book(book_id: int, owner_id: int) -> bool:
    """Faqat e'lon egasi o'chira oladi — owner_id mosligini tekshiradi."""
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE books SET is_active = 0 WHERE id = ? AND owner_id = ?",
            (book_id, owner_id),
        )
        return cursor.rowcount > 0
