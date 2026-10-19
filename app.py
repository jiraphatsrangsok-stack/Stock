from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime

app = Flask(__name__)
DB_NAME = "inventory.db"

def init_db():
    """สร้างตารางใน SQLite Database หากยังไม่มี"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # ตารางสินค้า
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sku TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                minStock INTEGER NOT NULL,
                image TEXT
            )
        ''')
        # ตารางประวัติความเคลื่อนไหว
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                productName TEXT NOT NULL,
                type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                note TEXT
            )
        ''')
        conn.commit()

# เรียกใช้งานฟังก์ชันสร้างฐานข้อมูลเมื่อเริ่มต้นเซิร์ฟเวอร์
init_db()

@app.route('/')
def index():
    """ส่งหน้า HTML หลัก"""
    return render_template('index.html')

# --- API Endpoints ---

@app.route('/api/products', methods=['GET'])
def get_products():
    """ดึงรายการสินค้าทั้งหมด"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM products ORDER BY id DESC")
        rows = cursor.fetchall()
        products = [dict(row) for row in rows]
    return jsonify(products)

@app.route('/api/products', methods=['POST'])
def add_product():
    """เพิ่มสินค้าใหม่"""
    data = request.json
    sku = data.get('sku', '').strip()
    name = data.get('name', '').strip()
    category = data.get('category', '').strip()
    quantity = int(data.get('quantity', 0))
    min_stock = int(data.get('minStock', 0))
    image = data.get('image', '')

    if not image:
        return jsonify({'error': 'กรุณาอัปโหลดรูปภาพสินค้า'}), 400

    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO products (sku, name, category, quantity, minStock, image) VALUES (?, ?, ?, ?, ?, ?)",
                (sku, name, category, quantity, min_stock, image)
            )
            # บันทึกประวัติรับเข้าสินค้า
            log_date = datetime.now().strftime('%d/%m/%Y, %H:%M:%S')
            cursor.execute(
                "INSERT INTO logs (date, productName, type, amount, note) VALUES (?, ?, ?, ?, ?)",
                (log_date, name, 'รับเข้า', quantity, 'เพิ่มสินค้าใหม่เข้าสู่ระบบ')
            )
            conn.commit()
            return jsonify({'message': 'เพิ่มสินค้าสำเร็จ', 'id': cursor.lastrowid})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'รหัสสินค้า (SKU) นี้มีในระบบแล้ว'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """แก้ไขข้อมูลสินค้า"""
    data = request.json
    sku = data.get('sku', '').strip()
    name = data.get('name', '').strip()
    category = data.get('category', '').strip()
    quantity = int(data.get('quantity', 0))
    min_stock = int(data.get('minStock', 0))
    image = data.get('image', '')

    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # ดึงข้อมูลเดิมเพื่อเปรียบเทียบส่วนต่างสต๊อก
            cursor.execute("SELECT quantity, image FROM products WHERE id = ?", (product_id,))
            old_product = cursor.fetchone()
            if not old_product:
                return jsonify({'error': 'ไม่พบสินค้าที่ต้องการแก้ไข'}), 404

            # หากไม่ได้ส่งรูปใหม่มา ให้ใช้รูปเดิม
            final_image = image if image else old_product['image']
            diff = quantity - old_product['quantity']

            cursor.execute(
                "UPDATE products SET sku=?, name=?, category=?, quantity=?, minStock=?, image=? WHERE id=?",
                (sku, name, category, quantity, min_stock, final_image, product_id)
            )

            # หากมีการเปลี่ยนแปลงจำนวนสต๊อก ให้บันทึกลง Logs
            if diff != 0:
                log_date = datetime.now().strftime('%d/%m/%Y, %H:%M:%S')
                log_type = 'รับเข้า' if diff > 0 else 'เบิกออก'
                cursor.execute(
                    "INSERT INTO logs (date, productName, type, amount, note) VALUES (?, ?, ?, ?, ?)",
                    (log_date, name, log_type, abs(diff), 'แก้ไขสต๊อกผ่านฟอร์ม')
                )

            conn.commit()
            return jsonify({'message': 'อัปเดตข้อมูลสำเร็จ'})
    except sqlite3.IntegrityError:
        return jsonify({'error': 'รหัสสินค้า (SKU) นี้มีในระบบแล้ว'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>/stock', methods=['PATCH'])
def adjust_stock(product_id):
    """ปรับเพิ่ม/ลดสต๊อกด่วน (+1 / -1)"""
    data = request.json
    change_amount = int(data.get('changeAmount', 0))

    try:
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            product = cursor.fetchone()

            if not product:
                return jsonify({'error': 'ไม่พบสินค้า'}), 404

            new_qty = product['quantity'] + change_amount
            if new_qty < 0:
                return jsonify({'error': 'ไม่สามารถปรับลดสต๊อกให้ติดลบได้'}), 400

            cursor.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, product_id))

            # บันทึกลง Logs
            log_date = datetime.now().strftime('%d/%m/%Y, %H:%M:%S')
            log_type = 'รับเข้า' if change_amount > 0 else 'เบิกออก'
            note = 'รับเข้าด่วน (+1)' if change_amount > 0 else 'เบิกออกด่วน (-1)'
            cursor.execute(
                "INSERT INTO logs (date, productName, type, amount, note) VALUES (?, ?, ?, ?, ?)",
                (log_date, product['name'], log_type, abs(change_amount), note)
            )

            conn.commit()
            return jsonify({'message': 'ปรับสต๊อกสำเร็จ', 'newQuantity': new_qty})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """ลบสินค้า"""
    try:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()
            return jsonify({'message': 'ลบสินค้าสำเร็จ'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """ดึงประวัติความเคลื่อนไหวทั้งหมด"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM logs ORDER BY id DESC")
        rows = cursor.fetchall()
        logs = [dict(row) for row in rows]
    return jsonify(logs)

if __name__ == '__main__':
    app.run(debug=True, port=5000)