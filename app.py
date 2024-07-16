from flask import Flask, render_template, request, redirect, url_for, flash, session, Response, jsonify
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import cv2
import threading
import pygame
import model
import os
import wagateway
import MySQLdb.cursors
import datetime
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Konfigurasi database
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'e-parkir'

# Konfigurasi direktori upload
UPLOAD_FOLDER = 'static/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

mysql = MySQL(app)

# Initialize YOLO model
model.init_model('static/model/parkir.pt')

# Initialize pygame mixer and load alarm sound
pygame.mixer.init()
alarm_sound = pygame.mixer.Sound("static/music/alarm.mp3")
model.set_alarm_sound(alarm_sound)

cap = None
frame_lock = threading.Lock()
current_frame = None
streaming = False

def fetch_alarm_time():
    with app.app_context():
        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT alarm_time FROM setting LIMIT 1")
            result = cur.fetchone()
            cur.close()
            if result:
                return int(result[0])  # Convert to integer
        except Exception as e:
            print(f"Error fetching alarm_time from database: {e}")
        return 10  # Default value if fetching fails

# Set max_time_in_zone from database or default to 10
max_time_in_zone = fetch_alarm_time()
model.set_max_time_in_zone(max_time_in_zone)

@app.route('/')
def index():
    session.clear()
    return render_template('login.html')

@app.route('/stop_feed')
def stop_feed():
    global streaming
    streaming = False
    model.stop_alarm()
    return jsonify(success=True)

@app.route('/stop_alarm')
def stop_alarm():
    model.stop_alarm()
    return jsonify(success=True)

@app.route('/current_frame')
def current_frame_route():
    global current_frame
    with frame_lock:
        if current_frame is not None:
            ret, buffer = cv2.imencode('.jpg', current_frame)
            frame = buffer.tobytes()
            return Response(frame, mimetype='image/jpeg')
    return '', 204

@app.route('/upload_video', methods=['POST'])
def upload_video():
    if 'video_file' not in request.files:
        return jsonify(success=False, message="No file part")

    file = request.files['video_file']
    if file.filename == '':
        return jsonify(success=False, message="No selected file")

    if file:
        filename = 'uploaded_video.mp4'
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        return jsonify(success=True, message="File successfully uploaded", file_path=file_path)

def save_alarms_to_db(triggered_alarms):
    with app.app_context():
        try:
            cur = mysql.connection.cursor()
            alarm_data = model.get_triggered_alarms_data(triggered_alarms)
            for alarm in alarm_data:
                id_inzone = alarm['id_inzone']
                label = alarm['label']
                tanggal_masuk = alarm['tanggal_masuk']
                total_waktu = alarm['total_waktu']
                query = """
                    INSERT INTO histori (id_inzone, label, tanggal_masuk, total_waktu)
                    VALUES (%s, %s, %s, %s)
                """
                cur.execute(query, (id_inzone, label, tanggal_masuk, total_waktu))
                mysql.connection.commit()

                # Send WhatsApp message
                send_whatsapp_message(label, tanggal_masuk, total_waktu)

            cur.close()
            print("Alarms saved to database.")
        except Exception as e:
            print(f"Error saving alarms to database: {e}")

def send_whatsapp_message(label, timestamp, total_waktu):
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT nomer_wa, message FROM setting WHERE id")
        result = cur.fetchone()
        cur.close()
        
        if result and result[0]:
            to_number = result[0]
            custom_message = result[1]
            print(f"Sending WhatsApp message to: {to_number}")
            
            # Konversi total_waktu dari detik menjadi menit dan detik
            minutes = int(total_waktu // 60)
            seconds = int(total_waktu % 60)
            
            message = (f"✉️ *{custom_message}* ⛔\n"
                       f"*Waktu Masuk:* {timestamp}\n"
                       f"*Total Waktu:* {minutes} menit {seconds} detik\n"
                       f"*Kendaraan Pelaku:* {label.upper()}")
                       
            result = wagateway.send_whatsapp_message(to_number, message)
            if "error" in result:
                print(f"Error sending WhatsApp message: {result['error']}")
            else:
                print(f"WhatsApp message sent successfully. Response: {result}")
        else:
            print("Error: No WhatsApp number found in the database")
    except Exception as e:
        print(f"Error fetching WhatsApp number from database: {e}")

def generate_frames(source):
    global cap, current_frame, streaming
    cap = cv2.VideoCapture(source)
    streaming = True
    while streaming:
        ret, frame = cap.read()
        if not ret:
            break

        # Resize frame to 1070 x 600
        frame = cv2.resize(frame, (1070, 600))

        # Process frame using YOLO model
        frame, triggered_alarms = model.process_frame(frame)

        # Save alarms to the database asynchronously
        if triggered_alarms:
            threading.Thread(target=save_alarms_to_db, args=(triggered_alarms,)).start()

        with frame_lock:
            current_frame = frame.copy()

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()

@app.route('/video_feed')
def video_feed():
    source_type = request.args.get('source_type')
    source = request.args.get('source')
    
    if source_type == 'file':
        source = os.path.join(app.config['UPLOAD_FOLDER'], source)
    elif source_type == 'ip':
        source = source

    return Response(generate_frames(source),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/setting')
def setting():
    if 'username' in session:
        return render_template('setting.html')  # Menggunakan template dashboard.html
    return redirect(url_for('index'))

@app.route('/get_settings', methods=['GET'])
def get_settings():
    with app.app_context():
        try:
            cur = mysql.connection.cursor()
            cur.execute("SELECT alarm_time, message, nomer_wa FROM setting LIMIT 1")
            result = cur.fetchone()
            cur.close()
            if result:
                alarm_time, message, nomer_wa = result
                return jsonify(success=True, alarm_time=alarm_time, message=message, nomer_wa=nomer_wa)
            return jsonify(success=False, message="Failed to fetch settings")
        except Exception as e:
            return jsonify(success=False, message=str(e))

@app.route('/update_settings', methods=['POST'])
def update_settings():
    data = request.get_json()
    alarm_time = data.get('alarm_time')
    message = data.get('message')
    nomer_wa = data.get('nomer_wa')
    
    if alarm_time is None or message is None or nomer_wa is None:
        return jsonify(success=False, message="Invalid input")
    
    try:
        cur = mysql.connection.cursor()
        cur.execute("UPDATE setting SET alarm_time = %s, message = %s, nomer_wa = %s", (alarm_time, message, nomer_wa))
        mysql.connection.commit()
        cur.close()
        
        # Update the model's max_time_in_zone with the new value
        model.set_max_time_in_zone(int(alarm_time))  # Convert to integer
        
        return jsonify(success=True, message="Settings updated successfully")
    except Exception as e:
        return jsonify(success=False, message=str(e))

@app.route('/login', methods=['POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM akun WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        if user and check_password_hash(user[3], password):
            session['username'] = username
            return jsonify({'success': True, 'redirect': url_for('dashboard')})
        else:
            message = 'Your password or email is incorrect. Contact our chat support on your bottom right for further steps.'
            return jsonify({'success': False, 'message': message})

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = generate_password_hash(request.form['password'])
        
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT * FROM akun WHERE email=%s", (email,))
        email_account = cursor.fetchone()

        cursor.execute("SELECT * FROM akun WHERE username=%s", (username,))
        username_account = cursor.fetchone()

        if email_account:
            cursor.close()
            flash('Email ini sudah terdaftar', 'danger')
            return redirect(url_for('register'))

        if username_account:
            cursor.close()
            flash('Username ini sudah terdaftar', 'danger')
            return redirect(url_for('register'))
        
        cursor.execute("INSERT INTO akun (username, email, password) VALUES (%s, %s, %s)", (username, email, password))
        mysql.connection.commit()
        cursor.close()
        flash('You are now registered and can log in', 'success')
        return redirect(url_for('register'))  # Redirect to register to show alert
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'username' in session:
        username = session.get('username')
        return render_template('dashboard.html', username=username)
    return redirect(url_for('index'))

@app.route('/editakun')
def editakun():
    if 'username' in session:
        return render_template('editakun.html')
    else:
        return redirect(url_for('index'))

@app.route('/get_akun', methods=['GET'])
def get_akun():
    if 'username' in session:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute('SELECT * FROM akun WHERE username=%s', (session['username'],))
        data = cursor.fetchone()
        return jsonify(data)
    else:
        return jsonify({"error": "Not authorized"}), 403

@app.route('/update_akun', methods=['POST'])
def update_akun():
    if 'username' in session:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = generate_password_hash(data.get('password'))

        cursor = mysql.connection.cursor()
        cursor.execute('UPDATE akun SET username=%s, email=%s, password=%s WHERE username=%s', (username, email, password, session['username']))
        mysql.connection.commit()
        
        # Update session with new username if it's changed
        session['username'] = username
        
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Not authorized"}), 403

@app.route('/barchart')
def barchart():
    if 'username' in session:
        return render_template('barchart.html')
    return redirect(url_for('index'))

@app.route('/get_barchart_data', methods=['GET'])
def get_barchart_data():
    # Tentukan awal dan akhir minggu ini
    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=6)

    # Query untuk mendapatkan data dari minggu ini
    query = """
    SELECT 
        DAYOFWEEK(tanggal_masuk) as day,
        label,
        COUNT(*) as count
    FROM histori
    WHERE tanggal_masuk BETWEEN %s AND %s
    GROUP BY day, label
    """
    cursor = mysql.connection.cursor()
    cursor.execute(query, (start_of_week, end_of_week))
    results = cursor.fetchall()
    cursor.close()

    # Inisialisasi data
    data = {
        "motor": [0] * 7,
        "mobil": [0] * 7,
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    }

    # Mapkan hasil query ke dalam data
    for row in results:
        day_index = row[0] - 2
        if day_index == -1:
            day_index = 6
        if row[1] == 'motor':
            data['motor'][day_index] = row[2]
        elif row[1] == 'mobil':
            data['mobil'][day_index] = row[2]

    return jsonify(data)

@app.route('/histori')
def histori():
    if 'username' in session:
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM histori ORDER BY tanggal_masuk DESC")
        histori_data = cursor.fetchall()
        return render_template('histori.html', histori_data=histori_data)
    return redirect(url_for('index'))

@app.route('/get_histori', methods=['GET'])
def get_histori():
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute('SELECT * FROM histori ORDER BY tanggal_masuk DESC')
    data = cursor.fetchall()
    cursor.close()
    return jsonify(data)

@app.route('/update_histori', methods=['POST'])
def update_histori():
    if 'username' in session:
        data = request.get_json()
        id = data.get('id')
        id_inzone = data.get('id_inzone')
        label = data.get('label')
        tanggal_masuk = data.get('tanggal_masuk')
        total_waktu = data.get('total_waktu')

        cursor = mysql.connection.cursor()
        cursor.execute('UPDATE histori SET id_inzone=%s, label=%s, tanggal_masuk=%s, total_waktu=%s WHERE id=%s',
                       (id_inzone, label, tanggal_masuk, total_waktu, id))
        mysql.connection.commit()
        cursor.close()
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Not authorized"}), 403

@app.route('/delete_histori', methods=['POST'])
def delete_histori():
    if 'username' in session:
        data = request.get_json()
        id = data.get('id')

        cursor = mysql.connection.cursor()
        cursor.execute('DELETE FROM histori WHERE id=%s', (id,))
        mysql.connection.commit()
        cursor.close()
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Not authorized"}), 403

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
