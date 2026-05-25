from flask import Flask, render_template, request, redirect, url_for, session, flash
from db import get_connection
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.secret_key = 'GameShop_Secret_Key_2026'


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def fetch_to_dict(cursor):
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_categories():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name_product, about_product_category FROM categories;")
    data = fetch_to_dict(cursor)
    cursor.close()
    conn.close()
    return data


def get_products(category_id=None):
    conn = get_connection()
    cursor = conn.cursor()
    if category_id:
        cursor.execute(
            "SELECT id, name_product, price, about_product, type_product FROM product WHERE category_id = %s;",
            (category_id,))
    else:
        cursor.execute("SELECT id, name_product, price, about_product, type_product FROM product;")
    data = fetch_to_dict(cursor)
    cursor.close()
    conn.close()
    return data


def create_user(mail, password, nickname):
    conn = get_connection()
    cursor = conn.cursor()
    hashed_pw = generate_password_hash(password)
    cursor.execute(
        "INSERT INTO users (mail, password, nickname, balance) VALUES (%s, %s, %s, %s)",
        (mail, hashed_pw, nickname, 0)
    )
    conn.commit()
    cursor.close()
    conn.close()


# Исправленная инициализация таблицы избранного специально под PostgreSQL
def init_favorites_db():
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                product_id INT NOT NULL,
                UNIQUE(user_id, product_id)
            );
        """)
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Ошибка при автоматической инициализации таблицы favorites: {e}")


# --- КОНТЕКСТНЫЙ ПРОЦЕССОР (Баланс и Корзина доступны везде) ---

@app.context_processor
def inject_user_data():
    user_id = session.get('user_id')
    cart_count = 0
    user_balance = 0
    if user_id:
        try:
            conn = get_connection()
            cursor = conn.cursor()
            # Считаем товары
            cursor.execute("SELECT SUM(quantity) FROM cart WHERE user_id = %s", (user_id,))
            res = cursor.fetchone()[0]
            cart_count = res if res else 0
            # Берем баланс
            cursor.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            user_balance = row[0] if row else 0
            cursor.close()
            conn.close()
        except Exception:
            pass
    return dict(cart_count=cart_count, user_balance=user_balance)


# --- ГЛАВНАЯ СТРАНИЦА И ВИДЖЕТ ---

# Навешиваем сразу два адреса на одну функцию
@app.route('/')
@app.route('/category/<int:cat_id>')
def index(cat_id=None):  # По умолчанию cat_id равен None (если зашли просто на /)
    user_id = session.get('user_id')
    categories = get_categories()

    # Если cat_id прилетел из URL-адреса (/category/3), берем его.
    # Если нет — проверяем, вдруг он пришел как GET-параметр.
    current_cat_id = cat_id if cat_id is not None else request.args.get('cat', type=int)

    # Передаем полученный ID в функцию получения товаров
    products = get_products(category_id=current_cat_id)

    # --- ОСТАЛЬНОЙ ТВОЙ КОД (БЛОК INSTANT И КОРЗИНА) ОСТАЕТСЯ БЕЗ ИЗМЕНЕНИЙ ---
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT type_product FROM product WHERE type_product IS NOT NULL;")
    db_types = [row[0] for row in cursor.fetchall()]

    selected_game = request.args.get('game', db_types[0] if db_types else 'игра')
    cursor.execute(
        "SELECT id, name_product, price FROM product WHERE type_product = %s ORDER BY price ASC;",
        (selected_game,)
    )
    instant_products = fetch_to_dict(cursor)
    default_price = instant_products[0]['price'] if instant_products else 0

    cart_items = []
    user_favorites = []
    if user_id:
        cursor.execute("SELECT product_id FROM cart WHERE user_id = %s", (user_id,))
        cart_items = [row[0] for row in cursor.fetchall()]
        try:
            cursor.execute("SELECT product_id FROM favorites WHERE user_id = %s", (user_id,))
            user_favorites = [row[0] for row in cursor.fetchall()]
        except Exception:
            conn.rollback()

    cursor.close()
    conn.close()

    return render_template(
        'index.html',
        categories=categories,
        products=products,
        cart_items=cart_items,
        favorites=user_favorites,
        db_types=db_types,
        selected_game=selected_game,
        instant_products=instant_products,
        default_price=default_price,
        current_cat_id=current_cat_id  # Передаем в HTML, чтобы кнопки в меню горели классом active
    )
# --- РОУТ МГНОВЕННОГО ЧЕКАУТА (ОЧИЩЕННЫЙ ОТ ХВОСТОВ) ---
# --- РОУТ МГНОВЕННОГО ЧЕКАУТА (ПОЛНОСТЬЮ ИСПРАВЛЕННЫЙ) ---
@app.route('/instant_checkout', methods=['POST'])
def instant_checkout():
    # 1. Забираем данные, которые прилетели из HTML-формы
    email = request.form.get('email', '').strip()
    product_id = request.form.get('product_id')  # ID выбранного товара
    promo_input = request.form.get('promocode', '').strip()  # Промокод

    if not email or not product_id:
        flash("Пожалуйста, заполните Email и выберите товар!", "error")
        return redirect(url_for('index'))

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 2. ПРОВЕРЯЕМ ПОЛЬЗОВАТЕЛЯ (Существует ли он в базе)
        cursor.execute("SELECT id, balance FROM users WHERE mail = %s", (email,))
        user = cursor.fetchone()

        if not user:
            flash("Пользователь с такой почтой не найден!", "error")
            return redirect(url_for('index'))

        user_id = user[0]
        user_balance = user[1]

        # 3. ДОСТАЕМ ТОВАР (ИСПРАВЛЕНО: таблица product и поле name_product)
        cursor.execute("SELECT name_product, price FROM product WHERE id = %s", (product_id,))
        product = cursor.fetchone()

        if not product:
            flash("Товар не найден!", "error")
            return redirect(url_for('index'))

        product_name = product[0]
        base_price = product[1]  # Исходная стоимость товара
        discount = 0  # Изначально скидка равна нулю

        # 4. ПРОВЕРКА ПРОМОКОДА
        if promo_input:
            cursor.execute(
                "SELECT discount_percent FROM promocodes WHERE code = %s AND is_active = 1",
                (promo_input,)
            )
            promo_result = cursor.fetchone()

            if promo_result:
                discount = promo_result[0]  # Нашли процент скидки
                flash(f"Промокод '{promo_input}' применен! Скидка {discount}%", "success")
            else:
                flash("Неверный или устаревший промокод!", "error")

        # 5. Считаем финальную стоимость товара со скидкой
        final_price = int(base_price * (1 - discount / 100))

        # 6. ПРОВЕРКА БАЛАНСА
        if user_balance < final_price:
            flash(f"Недостаточно средств! Стоимость: {final_price} ₽, ваш баланс: {user_balance} ₽.", "error")
            return redirect(url_for('index'))

        # 7. СПИСАНИЕ БАЛАНСА
        cursor.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (final_price, user_id))

        # 8. СОЗДАНИЕ ЗАКАЗА В БД (Генерируем order_id автоматически средствами PostgreSQL)
        # Если у тебя есть таблица заказов (например, orders), раскомментируй строки ниже:
        # cursor.execute(
        #     "INSERT INTO orders (user_id, product_id, final_price) VALUES (%s, %s, %s) RETURNING id;",
        #     (user_id, product_id, final_price)
        # )
        # order_id = cursor.fetchone()[0]

        # Если таблицы заказов пока нет, временно сгенерируем случайный номер:
        import random
        order_id = random.randint(100000, 999999)

        # Сохраняем все транзакции в базе данных
        conn.commit()

        # Выводим уведомление (как у тебя на скриншоте image_4341ef.png)
        flash(f"🎉 Вы успешно приобрели {product_name}! С баланса списано {final_price} ₽. Номер заказа: #{order_id}",
              "success")
        return redirect(url_for('index'))

    except Exception as e:
        conn.rollback()
        flash(f"Произошла ошибка при обработке платежа: {e}", "error")
        return redirect(url_for('index'))

    finally:
        cursor.close()
        conn.close()
# --- КОРЗИНА СТРАНИЦА ---
@app.route('/cart')
def cart_page():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT p.id, p.name_product, p.price, c.quantity
        FROM cart c
        JOIN product p ON c.product_id = p.id
        WHERE c.user_id = %s
        ORDER BY c.id ASC
    """
    cursor.execute(query, (user_id,))
    items = fetch_to_dict(cursor)
    total = sum(item['price'] * item['quantity'] for item in items)
    cursor.close()
    conn.close()
    return render_template('cart.html', products=items, total=total)


# --- ЛОГИКА КОРЗИНЫ ---

def logic_add(product_id):
    user_id = session.get('user_id')
    if not user_id:
        return False
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM cart WHERE user_id = %s AND product_id = %s", (user_id, product_id))
    if cursor.fetchone():
        cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id = %s AND product_id = %s",
                       (user_id, product_id))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, 1)", (user_id, product_id))
    conn.commit()
    cursor.close()
    conn.close()
    return True


@app.route('/add_to_cart/<int:product_id>')
def add_to_cart(product_id):
    if logic_add(product_id):
        return redirect(url_for('index') + '#catalog')
    return redirect(url_for('login'))


@app.route('/cart/add/<int:product_id>')
def add_to_cart_cart(product_id):
    logic_add(product_id)
    return redirect(url_for('cart_page'))


@app.route('/cart/remove/<int:product_id>')
def remove_one_cart(product_id):
    user_id = session.get('user_id')
    if user_id:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT quantity FROM cart WHERE user_id = %s AND product_id = %s", (user_id, product_id))
        res = cursor.fetchone()
        if res and res[0] > 1:
            cursor.execute("UPDATE cart SET quantity = quantity - 1 WHERE user_id = %s AND product_id = %s",
                           (user_id, product_id))
        else:
            cursor.execute("DELETE FROM cart WHERE user_id = %s AND product_id = %s", (user_id, product_id))
        conn.commit()
        cursor.close()
        conn.close()
    return redirect(url_for('cart_page'))


# --- ЛОГИКА ИЗБРАННОГО ---

@app.route('/add_to_favorites/<int:product_id>')
def add_to_favorites(product_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM favorites WHERE user_id = %s AND product_id = %s", (user_id, product_id))
    favorite = cursor.fetchone()

    if favorite:
        cursor.execute("DELETE FROM favorites WHERE user_id = %s AND product_id = %s", (user_id, product_id))
    else:
        cursor.execute("INSERT INTO favorites (user_id, product_id) VALUES (%s, %s)", (user_id, product_id))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(request.referrer or url_for('index'))


@app.route('/favorites')
def favorites_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    categories = get_categories()

    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT p.id, p.name_product, p.price, p.about_product, p.type_product
        FROM favorites f
        JOIN product p ON f.product_id = p.id
        WHERE f.user_id = %s
    """
    cursor.execute(query, (user_id,))
    products = fetch_to_dict(cursor)

    user_favorites = [p['id'] for p in products]

    cursor.close()
    conn.close()

    return render_template('index.html', categories=categories, products=products, favorites=user_favorites)


# --- РЕГИСТРАЦИЯ И ВХОД ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nick = request.form.get('nickname')
        mail = request.form.get('mail')
        pw = request.form.get('password')
        if not nick or not mail or not pw:
            return render_template('register.html', error="Заполни все поля!")

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE mail = %s", (mail,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return render_template('register.html', error="Эта почта уже занята!")

        create_user(mail, pw, nick)
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        mail = request.form.get('mail')
        pw = request.form.get('password')
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, password, nickname FROM users WHERE mail = %s", (mail,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user and check_password_hash(user[1], pw):
            session['user_id'] = user[0]
            session['user_name'] = user[2]
            return redirect(url_for('index'))
        return render_template('login.html', error="Неверная почта или пароль!")
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if 'avatar' not in request.files:
        return redirect(request.referrer or url_for('index'))

    file = request.files['avatar']
    allowed_extensions = {'png', 'jpg', 'jpeg', 'webp', 'gif'}

    if file and '.' in file.filename and file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
        user_id = session['user_id']
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"avatar_user_{user_id}.{ext}"

        upload_dir = os.path.join('static', 'uploads')
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)

        filepath = os.path.join(upload_dir, filename)
        file.save(filepath)

        session['user_avatar'] = filename

        conn = get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE users SET avatar = %s WHERE id = %s", (filename, user_id))
            conn.commit()
        except Exception as e:
            print(f"Ошибка сохранения аватарки в бд: {e}")
        finally:
            cursor.close()
            conn.close()

    return redirect(request.referrer or url_for('index'))


# --- НАСТРОЕЧНЫЕ РОУТЫ ---

@app.route('/settings')
def settings_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('settings.html')


@app.route('/settings/update_profile', methods=['POST'])
def update_profile_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    new_nick = request.form.get('nickname')
    user_id = session['user_id']

    if not new_nick:
        return render_template('settings.html', error="Никнейм не может быть пустым!")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET nickname = %s WHERE id = %s", (new_nick, user_id))
    conn.commit()
    cursor.close()
    conn.close()

    session['user_name'] = new_nick
    return render_template('settings.html', success="Личные данные успешно обновлены!")


@app.route('/settings/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_pw = request.form.get('current_password')
    new_pw = request.form.get('new_password')
    user_id = session['user_id']

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    if user and check_password_hash(user[0], current_pw):
        hashed_new_pw = generate_password_hash(new_pw)
        cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_new_pw, user_id))
        conn.commit()
        cursor.close()
        conn.close()
        return render_template('settings.html', success="Пароль успешно изменен!")

    cursor.close()
    conn.close()
    return render_template('settings.html', error="Неверный текущий пароль!")


if __name__ == '__main__':
    init_favorites_db()  # Таблица favorites теперь создается без ошибок синтаксиса
    app.run(debug=True)