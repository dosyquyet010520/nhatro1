import streamlit as st
import os
import hashlib
import csv
from datetime import datetime, timedelta
import pandas as pd
import base64
import re
import urllib.parse

# --- TÍCH HỢP THƯ VIỆN GOOGLE SHEETS ---
HAS_GS_LIBS = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAS_GS_LIBS = True
except ImportError:
    pass

# --- HÀM BẢO MẬT & CHỐNG HACK ĐƯỜNG DẪN (SAN|TIZE) ---
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def clean_filename(text):
    """Lọc bỏ toàn bộ ký tự lạ, chỉ giữ lại chữ, số và dấu gạch ngang để bảo mật file/sheet"""
    return re.sub(r'[^a-zA-Z0-9_-]', '', str(text))

# --- KẾT NỐI VÀ KHỞI TẠO GOOGLE SHEETS ---
GS_SHEET = None
if HAS_GS_LIBS:
    try:
        if "gcp_service_account" in st.secrets:
            # Sao chép cấu hình từ secrets ra một dict mới để chỉnh sửa
            gcp_info = dict(st.secrets["gcp_service_account"])
            
            # Tự động sửa định dạng private_key: thay thế \n thực tế thành ký tự xuống dòng chuẩn
            if "private_key" in gcp_info:
                gcp_info["private_key"] = gcp_info["private_key"].replace("\\n", "\n")
                
            scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(gcp_info, scopes=scope)
            client = gspread.authorize(creds)
            
            spreadsheet_id = st.secrets.get("spreadsheet_id")
            if spreadsheet_id:
                GS_SHEET = client.open_by_key(spreadsheet_id)
            else:
                GS_SHEET = client.open_by_key("12vYA8p8T2GHu4DBPW4HqIi01uUmzvkBxZ4Y28UE-R9I")
    except Exception as e:
        st.error(f"Lỗi kết nối Google Sheets: {e}")
        GS_SHEET = None

def get_or_create_worksheet(name, headers):
    if GS_SHEET is None:
        return None
    try:
        return GS_SHEET.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        try:
            ws = GS_SHEET.add_worksheet(title=name, rows="1000", cols=str(len(headers)))
            ws.append_row(headers)
            return ws
        except:
            return None
    except:
        return None

def gs_read_rows(name, headers):
    ws = get_or_create_worksheet(name, headers)
    if ws:
        try:
            data = ws.get_all_records()
            return [{k: str(v) for k, v in row.items()} for row in data]
        except:
            rows = ws.get_all_values()
            if len(rows) <= 1: return []
            hdrs = rows[0]
            res = []
            for r in rows[1:]:
                row_dict = {}
                for i, h in enumerate(hdrs):
                    row_dict[h] = r[i] if i < len(r) else ""
                res.append(row_dict)
            return res
    return []

def gs_write_rows(name, headers, list_of_dicts):
    ws = get_or_create_worksheet(name, headers)
    if ws:
        try:
            ws.clear()
            matrix = [headers]
            for d in list_of_dicts:
                matrix.append([str(d.get(h, "")) for h in headers])
            ws.update('A1', matrix)
            return True
        except Exception as e:
            st.error(f"Lỗi đồng bộ đám mây ({name}): {e}")
    return False

def gs_append_row(name, headers, row_values):
    ws = get_or_create_worksheet(name, headers)
    if ws:
        try:
            ws.append_row([str(v) for v in row_values])
            return True
        except Exception as e:
            st.error(f"Lỗi ghi đè dữ liệu đám mây ({name}): {e}")
    return False

# --- CẤU HÌNH ĐƯỜNG DẪN FILE CSV DỰ PHÒNG & FIELDNAMES ---
USER_DB = "users_db.csv"
AUDIT_LOG_FILE = "audit_logs.csv"

fieldnames = ["Tháng", "Số Phòng", "Tên Khách", "Số Người", "Tiền Phòng", "Điện Cũ", "Điện Mới", "Tiền Điện", "Nước Cũ", "Nước Mới", "Tiền Nước", "Tiền Rác", "Tiền Giặt", "Phát Sinh", "Tên Phát Sinh", "Tổng Cộng", "Ảnh Điện", "Ảnh Nước", "Số Ngày Ở", "Loại Biến Động"]
cust_fieldnames = ["Họ Tên", "Số Điện Thoại", "Số CCCD", "Ngày Sinh", "Quê Quán", "Phòng Ở", "Ngày Vào Ở", "Ngày Rời Đi", "Trạng Thái", "Ghi Chú", "Vai Trò"]

def log_action(username, action, details=""):
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    headers = ["Timestamp", "User", "Action", "Details"]
    row = [timestamp, username, action, details]
    
    if GS_SHEET:
        gs_append_row("audit_logs", headers, row)
    else:
        file_exists = os.path.exists(AUDIT_LOG_FILE)
        with open(AUDIT_LOG_FILE, mode="a", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(headers)
            writer.writerow(row)

def load_users():
    users = []
    headers = ["username", "password", "email", "status"]
    if GS_SHEET:
        users = gs_read_rows("users_db", headers)
    else:
        if os.path.exists(USER_DB):
            with open(USER_DB, mode="r", encoding="utf-8-sig") as f:
                users = list(csv.DictReader(f))
                
    for u in users:
        if "status" not in u:
            u["status"] = "active"
                
    try:
        admin_user = st.secrets.get("admin_username", "admin")
        admin_password_raw = st.secrets.get("admin_password", "admin123")
    except Exception:
        admin_user = "admin"
        admin_password_raw = "admin123"
    
    admin_exists = any(u["username"] == admin_user for u in users)
    if not admin_exists:
        users.append({
            "username": admin_user, 
            "password": hash_password(admin_password_raw), 
            "email": "admin@gmail.com",
            "status": "active"
        })
    return users

def save_users(users_list):
    headers = ["username", "password", "email", "status"]
    if GS_SHEET:
        cleaned_users = [{k: str(v) for k, v in u.items() if k in headers} for u in users_list]
        gs_write_rows("users_db", headers, cleaned_users)
    else:
        with open(USER_DB, mode="w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            cleaned_users = [{k: v for k, v in u.items() if k in headers} for u in users_list]
            writer.writerows(cleaned_users)

def login_user(username, password):
    users = load_users()
    hashed = hash_password(password)
    for u in users:
        if u["username"] == username and u["password"] == hashed:
            if u.get("status") == "locked":
                return "LOCKED"
            return "SUCCESS"
    return "FAILED"

def get_previous_month(current_month_str):
    try:
        dt = datetime.strptime(current_month_str, "%m/%Y")
        if dt.month == 1:
            return f"12/{dt.year - 1}"
        else:
            return f"{dt.month - 1:02d}/{dt.year}"
    except:
        return ""

def save_uploaded_image(uploaded_file, username, month, room, type_img):
    if uploaded_file is None:
        return ""
    clean_month = month.replace("/", "_")
    safe_user = clean_filename(username)
    safe_room = clean_filename(room)
    
    dir_path = f"img_{safe_user}/{clean_month}"
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    
    ext = os.path.splitext(uploaded_file.name)[1] or ".jpg"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{safe_room}_{type_img}_{timestamp}{ext}"
    full_path = os.path.join(dir_path, file_name)
    
    with open(full_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return full_path

def get_img_base64(path):
    if path and os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except:
            pass
    return ""

# --- CẤU HÌNH GIAO DIỆN ---
st.set_page_config(page_title="Hệ Thống Quản Lý Nhà Trọ", layout="wide")

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.username = ""

if "show_register" not in st.session_state:
    st.session_state.show_register = False

if "invoice_room" not in st.session_state:
    st.session_state.invoice_room = None

if "edit_cust_index" not in st.session_state:
    st.session_state.edit_cust_index = None

if "admin_unlocked" not in st.session_state:
    st.session_state.admin_unlocked = False

if "admin_last_active" not in st.session_state:
    st.session_state.admin_last_active = datetime.now()

# --- GIAO DIỆN ĐĂNG NHẬP ---
if not st.session_state.logged_in:
    st.title("🏨 Hệ Thống Quản Lý Nhà Trọ")
    st.markdown("---")
    col_space1, col_login, col_space2 = st.columns([1, 2, 1])
    
    with col_login:
        if not st.session_state.show_register:
            st.markdown("### 🔑 ĐĂNG NHẬP")
            with st.form(key="login_form"):
                username = st.text_input("Tên tài khoản")
                password = st.text_input("Mật khẩu", type="password")
                submit_button = st.form_submit_button(label="🚀 Đăng Nhập")
                
                if submit_button:
                    login_status = login_user(username, password)
                    if login_status == "SUCCESS":
                        st.session_state.logged_in = True
                        st.session_state.username = username
                        log_action(username, "Đăng nhập", "Đăng nhập hệ thống thành công")
                        st.success(f"Chào mừng {username}!")
                        st.rerun()
                    elif login_status == "LOCKED":
                        log_action(username, "Đăng nhập thất bại", "Tài khoản đang bị khóa")
                        st.error("Tài khoản của bạn đã bị khóa bởi Admin. Vui lòng liên hệ quản trị viên!")
                    else:
                        st.error("Sai tài khoản hoặc mật khẩu!")
            
            if st.button("🆕 Đăng ký tài khoản mới"):
                st.session_state.show_register = True
                st.rerun()
        else:
            st.markdown("### 📝 ĐĂNG KÝ TÀI KHOẢN MỚI")
            with st.form(key="register_form", clear_on_submit=True):
                new_username = st.text_input("Tên tài khoản muốn đăng ký *")
                new_email = st.text_input("Địa chỉ Email *")
                new_password = st.text_input("Mật khẩu *", type="password")
                confirm_password = st.text_input("Xác nhận lại mật khẩu *", type="password")
                
                register_submit = st.form_submit_button(label="✨ Tạo tài khoản")
                
                if register_submit:
                    if not new_username or not new_email or not new_password:
                        st.error("Vui lòng điền đầy đủ tất cả các trường có dấu (*)")
                    elif new_password != confirm_password:
                        st.error("Mật khẩu xác nhận không khớp! Vui lòng nhập lại.")
                    elif clean_filename(new_username) != new_username:
                        st.error("Tên tài khoản chỉ được chứa chữ cái và chữ số, không chứa ký tự đặc biệt hoặc dấu cách!")
                    else:
                        current_users = load_users()
                        username_exists = any(u["username"].lower() == new_username.lower() for u in current_users)
                        
                        if username_exists:
                            st.error("Tên tài khoản này đã có người sử dụng! Vui lòng chọn tên khác.")
                        else:
                            new_row = [new_username, hash_password(new_password), new_email, "active"]
                            if GS_SHEET:
                                gs_append_row("users_db", ["username", "password", "email", "status"], new_row)
                            else:
                                file_exists = os.path.exists(USER_DB)
                                with open(USER_DB, mode="a", encoding="utf-8-sig", newline="") as f:
                                    writer = csv.writer(f)
                                    if not file_exists:
                                        writer.writerow(["username", "password", "email", "status"])
                                    writer.writerow(new_row)
                            
                            log_action(new_username, "Đăng ký tài khoản", f"Đăng ký tài khoản mới ({new_email})")
                            st.success(f"🎉 Đăng ký tài khoản '{new_username}' thành công! Vui lòng quay lại màn hình Đăng nhập.")
                            st.session_state.show_register = False
                            st.rerun()
            
            if st.button("⬅️ Quay lại Đăng nhập"):
                st.session_state.show_register = False
                st.rerun()

# --- GIAO DIỆN CHÍNH ---
else:
    safe_user = clean_filename(st.session_state.username)
    DATA_FILE = f"data_nhatro_{safe_user}.csv"
    CONFIG_FILE = f"config_{safe_user}.csv"
    CUSTOMER_FILE = f"customers_{safe_user}.csv"

    menu_options = ["🏠 Quản Lý Hóa Đơn", "👥 Quản Lý Khách Thuê", "📊 Tổng Hợp & Thống Kê"]
    
    is_admin = False
    try:
        if st.session_state.username == st.secrets.get("admin_username", "admin"):
            is_admin = True
    except Exception:
        if st.session_state.username == "admin":
            is_admin = True
            
    if is_admin:
        menu_options.append("👑 TRANG ADMIN")
        
    user_choice = st.sidebar.selectbox("Chức năng hệ thống", menu_options)
    st.sidebar.markdown("---")
    st.sidebar.write(f"👤 Tài khoản: **{st.session_state.username}**")
    
    if GS_SHEET:
        st.sidebar.success("☁️ Kết nối Cloud Sheets Hoạt động")
    else:
        st.sidebar.info("💾 Chế độ lưu File CSV Local (Offline)")

    with st.sidebar.expander("💾 Hộp Kỹ Thuật: Sao Lưu & Khôi Phục", expanded=False):
        st.caption("Tải backup hoặc khôi phục độc lập từng phần dữ liệu của hệ thống:")
        
        def get_file_bytes(file_path):
            if os.path.exists(file_path):
                with open(file_path, "rb") as f: return f.read()
            return b""
            
        db_bytes = get_file_bytes(DATA_FILE)
        if db_bytes:
            st.download_button("📥 Tải Backup Hóa Đơn & Thống Kê", data=db_bytes, file_name=DATA_FILE, mime="text/csv", width="stretch")
            
        cust_bytes = get_file_bytes(CUSTOMER_FILE)
        if cust_bytes:
            st.download_button("📥 Tải Backup Khách Thuê", data=cust_bytes, file_name=CUSTOMER_FILE, mime="text/csv", width="stretch")
            
        cfg_bytes = get_file_bytes(CONFIG_FILE)
        if cfg_bytes:
            st.download_button("📥 Tải Backup Cấu Hình Đơn Giá", data=cfg_bytes, file_name=CONFIG_FILE, mime="text/csv", width="stretch")
            
        st.markdown("---")
        st.markdown("**🔄 Khôi Phục Dữ Liệu Từ File CSV**")
        
        restore_type = st.selectbox(
            "Chọn loại dữ liệu muốn khôi phục:", 
            ["Hóa Đơn & Thống Kê", "Danh Sách Khách Thuê", "Cấu Hình Đơn Giá"]
        )
        uploaded_restore_file = st.file_uploader("📤 Chọn file CSV tương ứng", type=["csv"], key="uploader_sidebar")
        
        if uploaded_restore_file is not None:
            if st.button("🔥 Xác Nhận Khôi Phục", width="stretch", type="primary"):
                if restore_type == "Hóa Đơn & Thống Kê":
                    target_file = DATA_FILE
                elif restore_type == "Danh Sách Khách Thuê":
                    target_file = CUSTOMER_FILE
                else:
                    target_file = CONFIG_FILE
                    
                with open(target_file, "wb") as f:
                    f.write(uploaded_restore_file.getbuffer())
                
                log_action(st.session_state.username, "Khôi phục dữ liệu", f"Đã khôi phục file {restore_type}")
                st.success(f"🎉 Khôi phục dữ liệu '{restore_type}' thành công! Hệ thống đang làm mới...")
                st.rerun()

    if st.sidebar.button("🚪 Đăng Xuất", width="stretch"):
        log_action(st.session_state.username, "Đăng xuất", "Đăng xuất khỏi hệ thống")
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.session_state.invoice_room = None
        st.session_state.admin_unlocked = False
        st.rerun()

    # ==================== TRANG ADMIN ====================
    if user_choice == "👑 TRANG ADMIN":
        st.title("👑 Bảng Điều Khiển Admin")
        st.markdown("---")
        
        ADMIN_PIN = st.secrets.get("admin_pin", "888888")
        TIMEOUT_MINUTES = 5 
        
        if st.session_state.admin_unlocked:
            time_since_active = datetime.now() - st.session_state.admin_last_active
            if time_since_active > timedelta(minutes=TIMEOUT_MINUTES):
                st.session_state.admin_unlocked = False
                st.warning(f"⏳ Hết phiên làm việc (Quá {TIMEOUT_MINUTES} phút không thao tác). Vui lòng nhập lại mã PIN!")
            else:
                st.session_state.admin_last_active = datetime.now()

        if not st.session_state.admin_unlocked:
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.info("🔒 Vui lòng nhập mã PIN bảo mật để truy cập Trang Admin.")
                with st.form("admin_auth_form"):
                    pin_input = st.text_input("Mã PIN Admin", type="password")
                    submit_pin = st.form_submit_button("🚀 Xác nhận truy cập", use_container_width=True)

                    if submit_pin:
                        if pin_input == ADMIN_PIN:
                            st.session_state.admin_unlocked = True
                            st.session_state.admin_last_active = datetime.now()
                            st.success("Mở khóa thành công!")
                            st.rerun()
                        else:
                            st.error("Mã PIN không chính xác!")
        else:
            col_blank, col_lock = st.columns([4, 1])
            with col_lock:
                if st.button("🔒 Khóa lại Trang Admin", type="secondary", use_container_width=True):
                    st.session_state.admin_unlocked = False
                    st.rerun()
                    
            tab_users, tab_logs = st.tabs(["👥 Quản lý Tài Khoản & Doanh Thu", "📜 Nhật ký Hoạt động (Audit Log)"])
            
            with tab_users:
                users = load_users()
                st.info("💡 Bấm vào **'👁️ Xem chi tiết'** để xem thống kê doanh thu và số lượng phòng của từng tài khoản.")
                
                for idx, u in enumerate(users):
                    uname = u['username']
                    is_super_admin = (uname == st.secrets.get("admin_username", "admin"))
                    status_icon = "🟢 Hoạt động" if u.get("status", "active") == "active" else "🔴 Bị Khóa"
                    
                    with st.container():
                        col_info, col_action1, col_action2 = st.columns([3, 1, 1])
                        with col_info:
                            st.markdown(f"**👤 {uname}** | 📧 {u['email']} | Trạng thái: {status_icon}")
                        
                        if not is_super_admin:
                            with col_action1:
                                if u.get("status", "active") == "active":
                                    if st.button("🔒 Khóa tài khoản", key=f"lock_{uname}", use_container_width=True):
                                        users[idx]["status"] = "locked"
                                        save_users(users)
                                        log_action(st.session_state.username, "Khóa tài khoản", f"Đã khóa tài khoản {uname}")
                                        st.toast(f"Đã khóa {uname}", icon="🔒")
                                        st.rerun()
                                else:
                                    if st.button("🔓 Mở khóa", key=f"unlock_{uname}", use_container_width=True, type="primary"):
                                        users[idx]["status"] = "active"
                                        save_users(users)
                                        log_action(st.session_state.username, "Mở khóa tài khoản", f"Đã mở khóa tài khoản {uname}")
                                        st.toast(f"Đã mở khóa {uname}", icon="🔓")
                                        st.rerun()
                                        
                            with col_action2:
                                with st.popover("🔑 Reset Pass", use_container_width=True):
                                    new_pass = st.text_input(f"Nhập pass mới cho {uname}", key=f"newpass_{uname}", type="password")
                                    if st.button("Xác nhận đổi", key=f"confirm_pass_{uname}"):
                                        if new_pass:
                                            users[idx]["password"] = hash_password(new_pass)
                                            save_users(users)
                                            log_action(st.session_state.username, "Reset Mật khẩu", f"Đã reset mật khẩu cho {uname}")
                                            st.success(f"Đổi mật khẩu {uname} thành công!")
                                        else:
                                            st.error("Pass không được rỗng")
                        
                        with st.expander(f"👁️ Xem chi tiết thống kê của {uname}"):
                            target_safe_user = clean_filename(uname)
                            target_data_file = f"data_nhatro_{target_safe_user}.csv"
                            target_cust_file = f"customers_{target_safe_user}.csv"
                            
                            u_invoices = []
                            u_customers = []
                            
                            if GS_SHEET:
                                u_invoices = gs_read_rows(f"data_{target_safe_user}", fieldnames)
                            elif os.path.exists(target_data_file):
                                with open(target_data_file, mode="r", encoding="utf-8-sig") as f:
                                    u_invoices = list(csv.DictReader(f))
                                    
                            if GS_SHEET:
                                u_customers = gs_read_rows(f"customers_{target_safe_user}", cust_fieldnames)
                            elif os.path.exists(target_cust_file):
                                with open(target_cust_file, mode="r", encoding="utf-8-sig") as f:
                                    u_customers = list(csv.DictReader(f))
                                    
                            active_rooms = set(c["Phòng Ở"] for c in u_customers if c.get("Trạng Thái") == "Đang ở" and c.get("Phòng Ở"))
                            total_revenue = sum(int(float(inv.get("Tổng Cộng", 0) or 0)) for inv in u_invoices)
                            
                            recent_month = "Chưa có"
                            recent_revenue = 0
                            if u_invoices:
                                all_u_months = sorted(list(set(inv["Tháng"] for inv in u_invoices)), reverse=True)
                                if all_u_months:
                                    recent_month = all_u_months[0]
                                    recent_revenue = sum(int(float(inv.get("Tổng Cộng", 0) or 0)) for inv in u_invoices if inv["Tháng"] == recent_month)

                            sc1, sc2, sc3 = st.columns(3)
                            sc1.metric("Tổng doanh thu tích lũy", f"{total_revenue:,} đ")
                            sc2.metric("Số phòng đang cho thuê", f"{len(active_rooms)} phòng")
                            sc3.metric(f"Doanh thu kỳ {recent_month}", f"{recent_revenue:,} đ")
                            
                            st.caption(f"Đã lập tổng cộng {len(u_invoices)} hóa đơn trong lịch sử.")
                    st.markdown("---")

            with tab_logs:
                st.subheader("📜 Nhật ký các thao tác trên hệ thống")
                logs = []
                log_headers = ["Timestamp", "User", "Action", "Details"]
                
                if GS_SHEET:
                    logs = gs_read_rows("audit_logs", log_headers)
                else:
                    if os.path.exists(AUDIT_LOG_FILE):
                        with open(AUDIT_LOG_FILE, mode="r", encoding="utf-8-sig") as f:
                            logs = list(csv.DictReader(f))
                
                if logs:
                    df_logs = pd.DataFrame(logs)
                    try:
                        df_logs['Timestamp_DT'] = pd.to_datetime(df_logs['Timestamp'], format="%d/%m/%Y %H:%M:%S")
                        df_logs = df_logs.sort_values(by='Timestamp_DT', ascending=False).drop(columns=['Timestamp_DT'])
                    except:
                        df_logs = df_logs[::-1]
                    
                    log_users = ["Tất cả"] + list(df_logs['User'].unique())
                    filter_user = st.selectbox("Lọc theo tài khoản:", log_users)
                    
                    if filter_user != "Tất cả":
                        df_logs = df_logs[df_logs['User'] == filter_user]
                        
                    st.dataframe(df_logs, use_container_width=True, hide_index=True)
                else:
                    st.info("Chưa có dữ liệu nhật ký hoạt động.")

    # ==================== ĐỌC FILE HÓA ĐƠN CHUNG ====================
    all_rows = []
    if GS_SHEET:
        all_rows = gs_read_rows(f"data_{safe_user}", fieldnames)
    else:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader: all_rows.append(row)

    for row in all_rows:
        if "Ảnh Điện" not in row: row["Ảnh Điện"] = ""
        if "Ảnh Nước" not in row: row["Ảnh Nước"] = ""
        if "Số Ngày Ở" not in row: row["Số Ngày Ở"] = "30"
        if "Loại Biến Động" not in row: row["Loại Biến Động"] = "Tròn tháng"

    # ==================== ĐỌC DỮ LIỆU KHÁCH THUÊ ====================
    customers = []
    if GS_SHEET:
        customers = gs_read_rows(f"customers_{safe_user}", cust_fieldnames)
    else:
        if os.path.exists(CUSTOMER_FILE):
            with open(CUSTOMER_FILE, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader: customers.append(row)

    for row in customers:
        if "Vai Trò" not in row or not row["Vai Trò"]:
            row["Vai Trò"] = "Chủ hộ"
        if "Ngày Rời Đi" not in row:
            row["Ngày Rời Đi"] = ""

    active_rooms_dict = {}
    for c in customers:
        if c.get("Trạng Thái") == "Đang ở":
            room = c.get("Phòng Ở")
            if room:
                if room not in active_rooms_dict:
                    active_rooms_dict[room] = {"names": [], "chu_ho": "", "count": 0}
                if c.get("Vai Trò") == "Chủ hộ":
                    active_rooms_dict[room]["chu_ho"] = c["Họ Tên"]
                active_rooms_dict[room]["names"].append(c["Họ Tên"])
                active_rooms_dict[room]["count"] += 1

    # ==================== MỤC: QUẢN LÝ KHÁCH THUÊ ====================
    if user_choice == "👥 Quản Lý Khách Thuê":
        st.title("👥 Quản Lý Thông Tin Người Ở Trọ & Lịch Sử")
        st.markdown("---")
        
        if st.session_state.edit_cust_index is not None:
            st.subheader("📝 Hiệu Chỉnh Thông Tin Khách Thuê (Chủ Hộ)")
            idx = st.session_state.edit_cust_index
            current_cust = customers[idx]
            
            with st.form(key="edit_customer_form"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    e_name = st.text_input("Họ và Tên khách thuê *", value=current_cust["Họ Tên"])
                    e_phone = st.text_input("Số điện thoại", value=current_cust["Số Điện Thoại"])
                    e_room = st.text_input("Số phòng trọ *", value=current_cust["Phòng Ở"])
                with c2:
                    e_cccd = st.text_input("Số CCCD / Định danh", value=current_cust["Số CCCD"])
                    e_dob = st.text_input("Ngày tháng năm sinh", value=current_cust["Ngày Sinh"])
                    e_status = st.selectbox("Trạng thái cư trú", ["Đang ở", "Đã rời đi"], index=0 if current_cust.get("Trạng Thái") == "Đang ở" else 1)
                with c3:
                    e_hometown = st.text_input("Quê quán", value=current_cust["Quê Quán"])
                    e_date_in = st.text_input("Ngày vào ở", value=current_cust["Ngày Vào Ở"])
                    e_date_out = st.text_input("Ngày rời đi (Nếu có)", value=current_cust.get("Ngày Rời Đi", ""))
                
                st.markdown("---")
                e_note = st.text_area("Ghi chú (Tiền cọc, xe cộ...)", value=current_cust["Ghi Chú"], height=68)
                
                col_btn1, col_btn2 = st.columns([1, 5])
                with col_btn1:
                    save_edit = st.form_submit_button("💾 Cập Nhật")
                with col_btn2:
                    cancel_edit = st.form_submit_button("❌ Hủy bỏ")
                    
                if save_edit:
                    if e_name and e_room:
                        old_room = current_cust["Phòng Ở"]
                        old_status = current_cust["Trạng Thái"]
                        
                        customers[idx] = {
                            "Họ Tên": e_name, "Số Điện Thoại": e_phone, "Số CCCD": e_cccd,
                            "Ngày Sinh": e_dob, "Quê Quán": e_hometown, "Phòng Ở": e_room,
                            "Ngày Vào Ở": e_date_in, "Ngày Rời Đi": e_date_out, "Trạng Thái": e_status, "Ghi Chú": e_note,
                            "Vai Trò": current_cust.get("Vai Trò", "Chủ hộ")
                        }
                        
                        for c in customers:
                            if c.get("Phòng Ở") == old_room and c.get("Vai Trò") == "Người ở cùng" and c.get("Trạng Thái") == old_status:
                                c["Trạng Thái"] = e_status
                                c["Phòng Ở"] = e_room
                                if e_status == "Đã rời đi" and e_date_out:
                                    c["Ngày Rời Đi"] = e_date_out

                        if GS_SHEET:
                            cleaned_customers = [{k: str(v) for k, v in c.items() if k in cust_fieldnames} for c in customers]
                            gs_write_rows(f"customers_{safe_user}", cust_fieldnames, cleaned_customers)
                        else:
                            with open(CUSTOMER_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                                writer = csv.DictWriter(f, fieldnames=cust_fieldnames)
                                writer.writeheader()
                                cleaned_customers = [{k: v for k, v in c.items() if k in cust_fieldnames} for c in customers]
                                writer.writerows(cleaned_customers)
                                
                        log_action(st.session_state.username, "Cập nhật khách thuê", f"Sửa thông tin chủ hộ phòng {e_room}")
                        st.success("Đã cập nhật thông tin chủ hộ thành công!")
                        st.session_state.edit_cust_index = None
                        st.rerun()
                if cancel_edit:
                    st.session_state.edit_cust_index = None
                    st.rerun()
        else:
            st.subheader("✍️ Thêm Chủ Hộ Mới (Khách ký hợp đồng)")
            with st.form(key="add_customer_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                with c1:
                    c_name = st.text_input("Họ và Tên khách thuê *")
                    c_phone = st.text_input("Số điện thoại")
                    c_room = st.text_input("Xếp vào số phòng *")
                with c2:
                    c_cccd = st.text_input("Số CCCD / Định danh")
                    c_dob = st.text_input("Ngày tháng năm sinh (Ví dụ: 01/05/2000)")
                    c_date_in = st.date_input("Ngày bắt đầu vào ở", value=datetime.today()).strftime("%d/%m/%Y")
                with c3:
                    c_hometown = st.text_input("Quê quán (Tỉnh/Thành phố)")
                    c_note = st.text_area("Ghi chú thêm (Xe cộ, Tiền cọc...)", height=68)
                    
                submit_cust = st.form_submit_button("➕ Thêm Khách Thuê Vào Hệ Thống")
                if submit_cust:
                    if c_name and c_room:
                        if GS_SHEET:
                            gs_append_row(f"customers_{safe_user}", cust_fieldnames, [c_name, c_phone, c_cccd, c_dob, c_hometown, c_room, c_date_in, "", "Đang ở", c_note if c_note else "Không", "Chủ hộ"])
                        else:
                            file_exists = os.path.exists(CUSTOMER_FILE)
                            with open(CUSTOMER_FILE, mode="a", encoding="utf-8-sig", newline="") as f:
                                writer = csv.writer(f)
                                if not file_exists:
                                    writer.writerow(cust_fieldnames)
                                writer.writerow([c_name, c_phone, c_cccd, c_dob, c_hometown, c_room, c_date_in, "", "Đang ở", c_note if c_note else "Không", "Chủ hộ"])
                        
                        log_action(st.session_state.username, "Thêm khách thuê", f"Thêm chủ hộ {c_name} vào phòng {c_room}")
                        st.success(f"🎉 Đã thêm thành công Chủ hộ {c_name} vào phòng {c_room}!")
                        st.rerun()
                    else:
                        st.error("Vui lòng điền các trường bắt buộc (*): Họ tên và Số Phòng!")

        st.markdown("---")
        st.subheader("📋 Tra Cứu Danh Sách Khách Thuê")
        filter_status = st.radio("Bộ lọc danh sách:", ["Tất cả khách", "Đang ở 🟢", "Đã rời đi 🔴"], horizontal=True)
        
        filtered_customers = []
        for i, c in enumerate(customers):
            c["_orig_index"] = i
            if c.get("Vai Trò", "Chủ hộ") == "Chủ hộ":
                if filter_status == "Tất cả khách":
                    filtered_customers.append(c)
                elif filter_status == "Đang ở 🟢" and c.get("Trạng Thái") == "Đang ở":
                    filtered_customers.append(c)
                elif filter_status == "Đã rời đi 🔴" and c.get("Trạng Thái") == "Đã rời đi":
                    filtered_customers.append(c)

        if filtered_customers:
            display_data = [{k: v for k, v in item.items() if k not in ["_orig_index", "Vai Trò"]} for item in filtered_customers]
            st.dataframe(display_data, width="stretch")
            
            st.markdown("#### ⚡ Thao tác nhanh & Tra cứu người ở cùng")
            col_sel, col_act1, col_act2 = st.columns([3, 1, 1])
            with col_sel:
                target_sel = st.selectbox("Bấm chọn tên chủ hộ để xem danh sách thành viên ở cùng phòng:", range(len(filtered_customers)), 
                                          format_func=lambda x: f"Phòng {filtered_customers[x]['Phòng Ở']} - {filtered_customers[x]['Họ Tên']} ({filtered_customers[x].get('Trạng Thái','Đang ở')})")
                selected_chu_ho = filtered_customers[target_sel]
                orig_idx = selected_chu_ho["_orig_index"]
            
            with col_act1:
                if st.button("📝 Sửa thông tin chủ hộ", width="stretch"):
                    st.session_state.edit_cust_index = orig_idx
                    st.rerun()
            with col_act2:
                if st.button("🗑️ Xóa vĩnh viễn chủ hộ", width="stretch"):
                    target_room = selected_chu_ho["Phòng Ở"]
                    target_status = selected_chu_ho["Trạng Thái"]
                    customers = [c for c in customers if not (c.get("Phòng Ở") == target_room and c.get("Trạng Thái") == target_status)]
                    
                    if GS_SHEET:
                        cleaned_customers = [{k: str(v) for k, v in c.items() if k in cust_fieldnames} for c in customers]
                        gs_write_rows(f"customers_{safe_user}", cust_fieldnames, cleaned_customers)
                    else:
                        with open(CUSTOMER_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                            writer = csv.DictWriter(f, fieldnames=cust_fieldnames)
                            writer.writeheader()
                            cleaned_customers = [{k: v for k, v in c.items() if k in cust_fieldnames} for c in customers]
                            writer.writerows(cleaned_customers)
                            
                    log_action(st.session_state.username, "Xóa khách thuê", f"Đã xóa toàn bộ thành viên phòng {target_room}")
                    st.success(f"💥 Đã xóa vĩnh viễn Chủ hộ và thành viên tại Phòng {target_room}!")
                    st.session_state.edit_cust_index = None
                    st.rerun()
            
            st.markdown("---")
            col_title, col_save = st.columns([3, 1])
            with col_title:
                st.markdown(f"##### 👨‍👩‍👧‍👦 Danh sách thành viên ở cùng tại **Phòng {selected_chu_ho['Phòng Ở']}**")
            with col_save:
                save_members = st.button("💾 Lưu Thành Viên Phòng Này", key=f"save_mem_{selected_chu_ho['Phòng Ở']}", type="primary", width="stretch")
            
            co_tenants = [c for c in customers if c.get("Phòng Ở") == selected_chu_ho["Phòng Ở"] and c.get("Vai Trò") == "Người ở cùng" and c.get("Trạng Thái") == selected_chu_ho["Trạng Thái"]]
            co_tenants_data = [{
                "Họ Tên": c.get("Họ Tên", ""), "Số Điện Thoại": c.get("Số Điện Thoại", ""), "Số CCCD": c.get("Số CCCD", ""),
                "Ngày Sinh": c.get("Ngày Sinh", ""), "Quê Quán": c.get("Quê Quán", ""), "Ngày Vào Ở": c.get("Ngày Vào Ở", ""),
                "Ngày Rời Đi": c.get("Ngày Rời Đi", ""), "Ghi Chú": c.get("Ghi Chú", "")
            } for c in co_tenants]
            
            df_editor = pd.DataFrame(co_tenants_data, columns=["Họ Tên", "Số Điện Thoại", "Số CCCD", "Ngày Sinh", "Quê Quán", "Ngày Vào Ở", "Ngày Rời Đi", "Ghi Chú"])
            edited_df = st.data_editor(df_editor, num_rows="dynamic", width="stretch", key=f"grid_editor_{selected_chu_ho['Phòng Ở']}")
            
            if save_members:
                new_customers = [c for c in customers if not (c.get("Phòng Ở") == selected_chu_ho["Phòng Ở"] and c.get("Vai Trò") == "Người ở cùng" and c.get("Trạng Thái") == selected_chu_ho["Trạng Thái"])]
                date_now = datetime.today().strftime("%d/%m/%Y")
                for _, row in edited_df.iterrows():
                    name_val = str(row["Họ Tên"]).strip() if pd.notna(row["Họ Tên"]) else ""
                    if name_val:
                        date_in_val = str(row["Ngày Vào Ở"]).strip() if pd.notna(row["Ngày Vào Ở"]) else date_now
                        date_out_val = str(row["Ngày Rời Đi"]).strip() if pd.notna(row["Ngày Rời Đi"]) else ""
                        new_customers.append({
                            "Họ Tên": name_val, "Số Điện Thoại": str(row["Số Điện Thoại"]).strip() if pd.notna(row["Số Điện Thoại"]) else "",
                            "Số CCCD": str(row["Số CCCD"]).strip() if pd.notna(row["Số CCCD"]) else "", "Ngày Sinh": str(row["Ngày Sinh"]).strip() if pd.notna(row["Ngày Sinh"]) else "",
                            "Quê Quán": str(row["Quê Quán"]).strip() if pd.notna(row["Quê Quán"]) else "", "Phòng Ở": selected_chu_ho["Phòng Ở"],
                            "Ngày Vào Ở": date_in_val, "Ngày Rời Đi": date_out_val, "Trạng Thái": selected_chu_ho["Trạng Thái"],
                            "Ghi Chú": str(row["Ghi Chú"]).strip() if pd.notna(row["Ghi Chú"]) else "Không", "Vai Trò": "Người ở cùng"
                        })
                
                if GS_SHEET:
                    cleaned_rows = [{k: str(v) for k, v in c.items() if k in cust_fieldnames} for c in new_customers]
                    gs_write_rows(f"customers_{safe_user}", cust_fieldnames, cleaned_rows)
                else:
                    with open(CUSTOMER_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=cust_fieldnames)
                        writer.writeheader()
                        cleaned_rows = [{k: v for k, v in c.items() if k in cust_fieldnames} for c in new_customers]
                        writer.writerows(cleaned_rows)
                        
                log_action(st.session_state.username, "Cập nhật thành viên", f"Lưu danh sách người ở cùng phòng {selected_chu_ho['Phòng Ở']}")
                st.success("💾 Đã lưu danh sách thành viên phòng thành công!")
                st.rerun()
        else:
            st.info("Không tìm thấy dữ liệu khách thuê.")

    # ==================== MỤC: QUẢN LÝ HÓA ĐƠN ====================
    elif user_choice == "🏠 Quản Lý Hóa Đơn":
        def load_config():
            if GS_SHEET:
                rows = gs_read_rows(f"config_{safe_user}", ["dg_phong", "dg_dien", "dg_nuoc", "dg_rac", "dg_giat"])
                if rows: return rows[0]
            else:
                if os.path.exists(CONFIG_FILE):
                    with open(CONFIG_FILE, mode="r", encoding="utf-8-sig") as f:
                        reader = csv.DictReader(f)
                        for row in reader: return row
            return {"dg_phong": 2000000, "dg_dien": 4000, "dg_nuoc": 15000, "dg_rac": 30000, "dg_giat": 50000}

        def save_config(cfg):
            if GS_SHEET:
                gs_write_rows(f"config_{safe_user}", ["dg_phong", "dg_dien", "dg_nuoc", "dg_rac", "dg_giat"], [cfg])
            else:
                with open(CONFIG_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=["dg_phong", "dg_dien", "dg_nuoc", "dg_rac", "dg_giat"])
                    writer.writeheader()
                    writer.writerows([cfg])

        cfg = load_config()
        st.title(f"🏨 Phòng làm việc: {st.session_state.username}")
        
        with st.expander("⚙️ 1. CÀI ĐẶT ĐƠN GIÁ MẶC ĐỊNH (MỘT THÁNG 30 NGÀY)", expanded=False):
            c_cfg1, c_cfg2, c_cfg3 = st.columns(3)
            with c_cfg1:
                dg_phong = st.number_input("Tiền phòng cố định", value=int(cfg["dg_phong"]), step=50000)
                dg_dien = st.number_input("Giá 1 số điện", value=int(cfg["dg_dien"]), step=500)
            with c_cfg2:
                dg_nuoc = st.number_input("Giá 1 khối nước", value=int(cfg["dg_nuoc"]), step=1000)
                dg_rac = st.number_input("Tiền rác (VND/người/tháng)", value=int(cfg["dg_rac"]), step=5000)
            with c_cfg3:
                dg_giat = st.number_input("Tiền máy giặt (VND/người/tháng)", value=int(cfg["dg_giat"]), step=5000)
            if st.button("💾 Lưu cấu hình"):
                save_config({"dg_phong": dg_phong, "dg_dien": dg_dien, "dg_nuoc": dg_nuoc, "dg_rac": dg_rac, "dg_giat": dg_giat})
                log_action(st.session_state.username, "Cập nhật cấu hình", "Cập nhật đơn giá phòng/điện/nước")
                st.success("Đã cập nhật đơn giá thành công!")
                st.rerun()

        st.markdown("---")

        st.header("✍️ 2. Nhập & Hiệu Chỉnh Dữ Tại Hóa Đơn")
        col_ctrl1, col_ctrl2 = st.columns(2)
        
        # --- TỐI ƯU CHỌN THÁNG (BẰNG CÁCH CHỌN NĂM TRƯỚC) ---
        with col_ctrl1:
            current_year = datetime.now().year
            # Tạo danh sách năm từ 2025 đến năm hiện tại + 3 năm nữa để dùng lâu dài
            year_list = list(range(2025, current_year + 4))
            
            sub_col_y, sub_col_m = st.columns(2)
            with sub_col_y:
                selected_year = st.selectbox("Chọn Năm", year_list, index=year_list.index(current_year) if current_year in year_list else 0)
            with sub_col_m:
                selected_month = st.selectbox("Chọn Tháng", [f"{i:02d}" for i in range(1, 13)], index=datetime.now().month - 1)
                
            thang = f"{selected_month}/{selected_year}"
            
        with col_ctrl2:
            active_room_list = sorted(list(active_rooms_dict.keys()))
            if active_room_list:
                so_phong = st.selectbox("Chọn Số Phòng *", active_room_list)
            else:
                so_phong = st.text_input("Số Phòng")
                st.warning("⚠️ Hiện chưa có phòng nào đang ở.")

        existing_invoice_idx = None
        existing_invoice = None
        for idx, r in enumerate(all_rows):
            if r.get("Số Phòng") == so_phong and r.get("Tháng") == thang:
                existing_invoice_idx = idx; existing_invoice = r; break

        if existing_invoice is not None:
            st.info(f"💡 Đang ở chế độ chỉnh sửa hóa đơn phòng {so_phong} tháng {thang}.")
        
        st.markdown("**⚙️ Cấu hình chu kỳ thời gian (Chu kỳ mặc định chốt ngày 15)**")
        default_type_idx = 0
        saved_days = 30
        if existing_invoice:
            try: saved_days = int(existing_invoice.get("Số Ngày Ở", 30))
            except: saved_days = 30
            v_type = existing_invoice.get("Loại Biến Động", "Tròn tháng")
            if v_type == "Vào giữa kỳ": default_type_idx = 1
            elif v_type == "Rời đi sớm": default_type_idx = 2

        loai_chu_ky = st.radio("Tình trạng lưu trú tháng này của phòng:", 
                               ["Tròn tháng (Ở đủ chu kỳ từ 15 đến 15)", 
                                "Khách MỚI VÀO giữa kỳ (Tính từ ngày vào lẻ đến ngày 15)", 
                                "Khách RỜI ĐI sớm giữa kỳ (Tính từ ngày 15 đến ngày rời đi lẻ)"], 
                               index=default_type_idx)

        if loai_chu_ky == "Tròn tháng (Ở đủ chu kỳ từ 15 đến 15)":
            days_stayed = 30
            label_biendong = "Tròn tháng"
        else:
            days_stayed = st.number_input("Số ngày ở thực tế trong chu kỳ này:", min_value=1, max_value=30, value=saved_days if saved_days != 30 else 15, step=1)
            label_biendong = "Vào giữa kỳ" if "MỚI VÀO" in loai_chu_ky else "Rời đi sớm"
            st.info(f"💡 Hệ thống sẽ chia đơn giá mặc định cho 30 ngày và nhân với **{days_stayed} ngày** ở thực tế.")

        st.markdown("---")

        col1, col2, col3 = st.columns(3)
        with col1:
            if existing_invoice:
                default_name = existing_invoice.get("Tên Khách", "")
                default_count = int(existing_invoice.get("Số Người", 1))
                if saved_days != 30:
                    try: default_tphong = int(float(existing_invoice.get("Tiền Phòng", cfg["dg_phong"])) * 30 / saved_days)
                    except: default_tphong = int(cfg["dg_phong"])
                else:
                    default_tphong = int(existing_invoice.get("Tiền Phòng", cfg["dg_phong"]))
            else:
                default_name = active_rooms_dict[so_phong]["chu_ho"] if so_phong in active_rooms_dict and active_rooms_dict[so_phong]["chu_ho"] else ""
                default_count = active_rooms_dict[so_phong]["count"] if so_phong in active_rooms_dict else 1
                default_tphong = int(cfg["dg_phong"])

            ten_khach = st.text_input("Tên Khách Thuê", value=default_name)
            so_nguoi = st.number_input("Số Người Ở", min_value=1, value=default_count, step=1)
            tien_phong_goc = st.number_input("Tiền Phòng GỐC (Tròn tháng)", value=default_tphong, step=50000)
            
            tien_phong_tinh = int((tien_phong_goc / 30) * days_stayed)
            if days_stayed != 30:
                st.caption(f"💵 Tiền phòng lẻ ({days_stayed} ngày): **{tien_phong_tinh:,.0f} đ**")
            
        auto_dien_cu = 0; auto_nuoc_cu = 0
        thang_truoc = get_previous_month(thang)
        if so_phong and thang_truoc:
            for r in all_rows:
                if r.get("Số Phòng") == so_phong and r.get("Tháng") == thang_truoc:
                    auto_dien_cu = int(float(r.get("Điện Mới", 0) or 0))
                    auto_nuoc_cu = int(float(r.get("Nước Mới", 0) or 0)); break

        with col2:
            val_dien_cu = int(float(existing_invoice.get("Điện Cũ", auto_dien_cu))) if existing_invoice else auto_dien_cu
            val_dien_moi = int(float(existing_invoice.get("Điện Mới", auto_dien_cu))) if existing_invoice else auto_dien_cu
            dien_cu = st.number_input("Số điện CŨ", min_value=0, value=val_dien_cu, step=1)
            dien_moi = st.number_input("Số điện MỚI", min_value=0, value=val_dien_moi, step=1)
            so_dien_dung = max(0, dien_moi - dien_cu)
            tien_dien_tinh = so_dien_dung * int(cfg["dg_dien"])
            
            val_nuoc_cu = int(float(existing_invoice.get("Nước Cũ", auto_nuoc_cu))) if existing_invoice else auto_nuoc_cu
            val_nuoc_moi = int(float(existing_invoice.get("Nước Mới", auto_nuoc_cu))) if existing_invoice else auto_nuoc_cu
            nuoc_cu = st.number_input("Số nước CŨ", min_value=0, value=val_nuoc_cu, step=1)
            nuoc_moi = st.number_input("Số nước MỚI", min_value=0, value=val_nuoc_moi, step=1)
            so_nuoc_dung = max(0, nuoc_moi - nuoc_cu)
            tien_nuoc_tinh = so_nuoc_dung * int(cfg["dg_nuoc"])

        with col3:
            goc_rac = so_nguoi * int(cfg["dg_rac"])
            goc_giat = so_nguoi * int(cfg["dg_giat"])
            val_ten_ps = existing_invoice.get("Tên Phát Sinh", "") if existing_invoice else ""
            val_ps = int(float(existing_invoice.get("Phát Sinh", 0))) if existing_invoice else 0

            tien_rac_tinh = int((goc_rac / 30) * days_stayed)
            tien_giat_tinh = int((goc_giat / 30) * days_stayed)
            
            st.write(f"🗑️ Tiền rác gốc: {goc_rac:,.0f} đ ➔ Tính lẻ: {tien_rac_tinh:,.0f} đ")
            st.write(f"🧺 Tiền giặt gốc: {goc_giat:,.0f} đ ➔ Tính lẻ: {tien_giat_tinh:,.0f} đ")
            ten_phat_sinh = st.text_input("Tên phát sinh khác", value=val_ten_ps)
            tien_phat_sinh_val = st.number_input("Số tiền phát sinh khác", min_value=0, value=val_ps, step=10000)

        st.markdown("#### 📸 Minh Chứng Chỉ Số (Hình Ảnh)")
        img_col1, img_col2 = st.columns(2)
        clean_thang = thang.replace("/", "_")
        dynamic_key_suffix = f"{clean_thang}_{so_phong}"
        
        with img_col1:
            if existing_invoice and existing_invoice.get("Ảnh Điện"):
                st.image(existing_invoice["Ảnh Điện"], caption="Ảnh điện đang lưu", width=200)
                if st.button("🗑️ Xóa ảnh điện", key=f"del_img_elec_{dynamic_key_suffix}"):
                    try: os.remove(existing_invoice["Ảnh Điện"])
                    except: pass
                    all_rows[existing_invoice_idx]["Ảnh Điện"] = ""
                    
                    if GS_SHEET:
                        cleaned_rows = [{k: str(v) for k, v in r.items() if k in fieldnames} for r in all_rows]
                        gs_write_rows(f"data_{safe_user}", fieldnames, cleaned_rows)
                    else:
                        with open(DATA_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                            writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader(); writer.writerows(all_rows)
                    
                    log_action(st.session_state.username, "Xóa ảnh điện", f"Phòng {so_phong} tháng {thang}")
                    st.rerun()
            mode_elec = st.radio("Nguồn ảnh điện:", ["📁 Tải lên", "📷 Camera"], key=f"mode_elec_{dynamic_key_suffix}", horizontal=True)
            file_dien = st.file_uploader("Chọn ảnh điện", type=["jpg","png","jpeg"], key=f"up_dien_{dynamic_key_suffix}") if mode_elec == "📁 Tải lên" else st.camera_input("Chụp ảnh điện", key=f"cam_dien_{dynamic_key_suffix}")

        with img_col2:
            if existing_invoice and existing_invoice.get("Ảnh Nước"):
                st.image(existing_invoice["Ảnh Nước"], caption="Ảnh nước đang lưu", width=200)
                if st.button("🗑️ Xóa ảnh nước", key=f"del_img_water_{dynamic_key_suffix}"):
                    try: os.remove(existing_invoice["Ảnh Nước"])
                    except: pass
                    all_rows[existing_invoice_idx]["Ảnh Nước"] = ""
                    
                    if GS_SHEET:
                        cleaned_rows = [{k: str(v) for k, v in r.items() if k in fieldnames} for r in all_rows]
                        gs_write_rows(f"data_{safe_user}", fieldnames, cleaned_rows)
                    else:
                        with open(DATA_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                            writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader(); writer.writerows(all_rows)
                            
                    log_action(st.session_state.username, "Xóa ảnh nước", f"Phòng {so_phong} tháng {thang}")
                    st.rerun()
            mode_water = st.radio("Nguồn ảnh nước:", ["📁 Tải lên", "📷 Camera"], key=f"mode_water_{dynamic_key_suffix}", horizontal=True)
            file_nuoc = st.file_uploader("Chọn ảnh nước", type=["jpg","png","jpeg"], key=f"up_nuoc_{dynamic_key_suffix}") if mode_water == "📁 Tải lên" else st.camera_input("Chụp ảnh nước", key=f"cam_nuoc_{dynamic_key_suffix}")

        tong_cong = tien_phong_tinh + tien_dien_tinh + tien_nuoc_tinh + tien_rac_tinh + tien_giat_tinh + tien_phat_sinh_val
        st.markdown(f"### 💰 Tổng dự kiến phòng {so_phong}: <span style='color:red'>{tong_cong:,.0f} đ</span>", unsafe_allow_html=True)
        
        if existing_invoice is not None:
            if st.button("📝 Cập Nhật Hóa Đơn này", type="primary"):
                path_dien = save_uploaded_image(file_dien, st.session_state.username, thang, so_phong, "dien") if file_dien else existing_invoice.get("Ảnh Điện", "")
                path_nuoc = save_uploaded_image(file_nuoc, st.session_state.username, thang, so_phong, "nuoc") if file_nuoc else existing_invoice.get("Ảnh Nước", "")
                
                all_rows[existing_invoice_idx] = {
                    "Tháng": thang, "Số Phòng": so_phong, "Tên Khách": ten_khach, "Số Người": so_nguoi,
                    "Tiền Phòng": tien_phong_tinh, "Điện Cũ": dien_cu, "Điện Mới": dien_moi, "Tiền Điện": tien_dien_tinh,
                    "Nước Cũ": nuoc_cu, "Nước Mới": nuoc_moi, "Tiền Nước": tien_nuoc_tinh, "Tiền Rác": tien_rac_tinh,
                    "Tiền Giặt": tien_giat_tinh, "Phát Sinh": tien_phat_sinh_val, "Tên Phát Sinh": ten_phat_sinh if ten_phat_sinh else "Không",
                    "Tổng Cộng": tong_cong, "Ảnh Điện": path_dien, "Ảnh Nước": path_nuoc, "Số Ngày Ở": str(days_stayed), "Loại Biến Động": label_biendong
                }
                
                if GS_SHEET:
                    cleaned_rows = [{k: str(v) for k, v in r.items() if k in fieldnames} for r in all_rows]
                    gs_write_rows(f"data_{safe_user}", fieldnames, cleaned_rows)
                else:
                    with open(DATA_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader(); writer.writerows(all_rows)
                        
                log_action(st.session_state.username, "Cập nhật hóa đơn", f"HĐ Phòng {so_phong} tháng {thang}")
                st.success("Đã cập nhật thành công!")
                st.session_state.invoice_room = all_rows[existing_invoice_idx]
                st.rerun()
        else:
            if st.button("💾 Lưu Hóa Đơn Mới", type="primary"):
                path_dien = save_uploaded_image(file_dien, st.session_state.username, thang, so_phong, "dien") if file_dien else ""
                path_nuoc = save_uploaded_image(file_nuoc, st.session_state.username, thang, so_phong, "nuoc") if file_nuoc else ""
                
                if GS_SHEET:
                    gs_append_row(f"data_{safe_user}", fieldnames, [thang, so_phong, ten_khach, so_nguoi, tien_phong_tinh, dien_cu, dien_moi, tien_dien_tinh, nuoc_cu, nuoc_moi, tien_nuoc_tinh, tien_rac_tinh, tien_giat_tinh, tien_phat_sinh_val, ten_phat_sinh if ten_phat_sinh else "Không", tong_cong, path_dien, path_nuoc, str(days_stayed), label_biendong])
                else:
                    file_exists = os.path.exists(DATA_FILE)
                    with open(DATA_FILE, mode="a", encoding="utf-8-sig", newline="") as f:
                        writer = csv.writer(f)
                        if not file_exists: writer.writerow(fieldnames)
                        writer.writerow([thang, so_phong, ten_khach, so_nguoi, tien_phong_tinh, dien_cu, dien_moi, tien_dien_tinh, nuoc_cu, nuoc_moi, tien_nuoc_tinh, tien_rac_tinh, tien_giat_tinh, tien_phat_sinh_val, ten_phat_sinh if ten_phat_sinh else "Không", tong_cong, path_dien, path_nuoc, str(days_stayed), label_biendong])
                
                log_action(st.session_state.username, "Tạo Hóa Đơn Mới", f"Tạo HĐ Phòng {so_phong} tháng {thang}")
                st.success("Đã lưu thành công!")
                st.rerun()

        # --- TỐI ƯU BỘ LỌC XEM DỮ LIỆU THÁNG Ở MỤC XUẤT BIÊN LAI ---
        st.markdown("---")
        with st.expander("📊 3. THỐNG KÊ & XUẤT HÓA ĐƠN ĐÃ LƯU (BẤM ĐỂ MỞ TÌM KIẾM)", expanded=False):
            if all_rows:
                # Tách lấy các năm và tháng ĐÃ TỪNG CÓ dữ liệu hóa đơn để làm bộ lọc thông minh
                existing_years = sorted(list(set(r["Tháng"].split("/")[1] for r in all_rows if "/" in r["Tháng"])), reverse=True)
                if not existing_years:
                    existing_years = [str(datetime.now().year)]
                    
                st.markdown("**🔍 Chọn nhanh khoảng thời gian cần lọc biên lai:**")
                filter_col1, filter_col2 = st.columns(2)
                with filter_col1:
                    thang_loc_nam = st.selectbox("Lọc theo Năm", existing_years, key="filter_year_main")
                with filter_col2:
                    # Lọc ra các tháng có dữ liệu của năm đã chọn
                    available_months = sorted(list(set(r["Tháng"].split("/")[0] for r in all_rows if "/" in r["Tháng"] and r["Tháng"].split("/")[1] == thang_loc_nam)))
                    if not available_months:
                        available_months = [f"{i:02d}" for i in range(1, 13)]
                    thang_loc_thang = st.selectbox("Lọc theo Tháng", available_months, key="filter_month_main")
                
                thang_loc = f"{thang_loc_thang}/{thang_loc_nam}"
                
                col_list, col_invoice = st.columns([1.5, 1.5])
                
                with col_list:
                    st.markdown(f"#### 📋 Danh sách tháng {thang_loc}")
                    total_thang = 0
                    has_data_this_month = False
                    for i, r in enumerate(all_rows):
                        if r["Tháng"] == thang_loc:
                            has_data_this_month = True
                            tc = int(float(r.get("Tổng Cộng", 0) or 0))
                            total_thang += tc
                            c_text, c_inv_btn, c_del_btn = st.columns([6, 2, 1])
                            with c_text: st.write(f"🏠 **{r['Số Phòng']}** - {r['Tên Khách']} ➔ **{tc:,}đ**")
                            with c_inv_btn:
                                if st.button("🧾 Hóa đơn", key=f"inv_{i}"): st.session_state.invoice_room = r
                            with c_del_btn:
                                if st.button("❌", key=f"del_{i}"):
                                    deleted_room = all_rows[i]['Số Phòng']
                                    all_rows.pop(i)
                                    
                                    if GS_SHEET:
                                        cleaned_rows = [{k: str(v) for k, v in row.items() if k in fieldnames} for row in all_rows]
                                        gs_write_rows(f"data_{safe_user}", fieldnames, cleaned_rows)
                                    else:
                                        with open(DATA_FILE, mode="w", encoding="utf-8-sig", newline="") as f:
                                            writer = csv.DictWriter(f, fieldnames=fieldnames); writer.writeheader(); writer.writerows(all_rows)
                                            
                                    log_action(st.session_state.username, "Xóa Hóa Đơn", f"Xóa HĐ Phòng {deleted_room} tháng {thang_loc}")
                                    st.session_state.invoice_room = None; st.rerun()
                    
                    if has_data_this_month:
                        st.markdown(f"### 💰 Tổng thu tháng {thang_loc}: **{total_thang:,.0f} VNĐ**")
                    else:
                        st.info(f"Chưa có hóa đơn nào được lưu trong tháng {thang_loc}")

                with col_invoice:
                    if st.session_state.invoice_room and st.session_state.invoice_room.get("Tháng") == thang_loc:
                        inv = st.session_state.invoice_room
                        so_nguoi_inv = int(float(inv.get('Số Người') or 1))
                        dien_cu_inv = int(float(inv.get('Điện Cũ') or 0)); dien_moi_inv = int(float(inv.get('Điện Mới') or 0))
                        nuoc_cu_inv = int(float(inv.get('Nước Cũ') or 0)); nuoc_moi_inv = int(float(inv.get('Nước Mới') or 0))
                        dien_dung = max(0, dien_moi_inv - dien_cu_inv); nuoc_dung = max(0, nuoc_moi_inv - nuoc_cu_inv)
                        r_days = int(float(inv.get("Số Ngày Ở", 30)))
                        v_type = inv.get("Loại Biến Động", "Tròn tháng")

                        try:
                            dt_current = datetime.strptime(inv['Tháng'], "%m/%Y")
                            date_15_this_month = datetime(dt_current.year, dt_current.month, 15)
                            
                            if v_type == "Tròn tháng" or r_days == 30:
                                if dt_current.month == 1:
                                    date_15_last_month = datetime(dt_current.year - 1, 12, 15)
                                else:
                                    date_15_last_month = datetime(dt_current.year, dt_current.month - 1, 15)
                                str_date_range = f"Từ ngày {date_15_last_month.strftime('%d/%m/%Y')} đến ngày {date_15_this_month.strftime('%d/%m/%Y')}"
                            
                            elif v_type == "Vào giữa kỳ":
                                date_start_obj = date_15_this_month - timedelta(days=(r_days - 1))
                                str_date_range = f"Từ ngày {date_start_obj.strftime('%d/%m/%Y')} đến ngày {date_15_this_month.strftime('%d/%m/%Y')} (Khách dọn vào ở lẻ)"
                            
                            elif v_type == "Rời đi sớm":
                                if dt_current.month == 1:
                                    date_15_last_month = datetime(dt_current.year - 1, 12, 15)
                                else:
                                    date_15_last_month = datetime(dt_current.year, dt_current.month - 1, 15)
                                date_end_actual = date_15_last_month + timedelta(days=r_days)
                                str_date_range = f"Từ ngày {date_15_last_month.strftime('%d/%m/%Y')} đến ngày {date_end_actual.strftime('%d/%m/%Y')} (Khách trả phòng sớm)"
                        except:
                            str_date_range = f"Chu kỳ thanh toán {r_days} ngày"

                        st.markdown("#### 🧾 CHI TIẾT BIÊN LAI")

                        phat_sinh_html = ""
                        if inv.get('Tên Phát Sinh') != "Không" and inv.get('Phát Sinh'):
                            val_ps = int(float(inv.get('Phát Sinh', 0)))
                            if val_ps > 0:
                                phat_sinh_html = f"<tr><td style='text-align: left; padding: 8px 0;'>6. Khác ({inv.get('Tên Phát Sinh')})</td><td>-</td><td>-</td><td>-</td><td style='text-align: right;'>{val_ps:,} đ</td></tr>"

                        t_phong = int(float(inv.get('Tiền Phòng', 0) or 0))
                        t_dien = int(float(inv.get('Tiền Điện', 0) or 0))
                        t_nuoc = int(float(inv.get('Tiền Nước', 0) or 0))
                        t_rac = int(float(inv.get('Tiền Rác', 0) or 0))
                        t_giat = int(float(inv.get('Tiền Giặt', 0) or 0))
                        t_tong = int(float(inv.get('Tổng Cộng', 0) or 0))

                        thang_hien_tai = inv.get("Tháng", "")
                        phong_hien_tai = inv.get("Số Phòng", "")
                        thang_truoc_str = get_previous_month(thang_hien_tai)
                        
                        old_inv = None
                        for r in all_rows:
                            if r.get("Số Phòng") == phong_hien_tai and r.get("Tháng") == thang_truoc_str:
                                old_inv = r; break

                        b64_dien_moi = get_img_base64(inv.get("Ảnh Điện"))
                        b64_nuoc_moi = get_img_base64(inv.get("Ảnh Nước"))
                        b64_dien_cu = get_img_base64(old_inv.get("Ảnh Điện")) if old_inv else ""
                        b64_nuoc_cu = get_img_base64(old_inv.get("Ảnh Nước")) if old_inv else ""

                        img_html_block = ""
                        if b64_dien_cu or b64_dien_moi:
                            img_html_block += '<div style="width: 100%; text-align: center; margin-bottom: 20px;">'
                            img_html_block += '<p style="font-size:14px; font-weight:bold; color:black; margin-bottom:5px;">⚡ MINH CHỨNG CHỈ SỐ ĐIỆN:</p>'
                            img_html_block += '<div style="display: flex; justify-content: center; gap: 15px;">'
                            if b64_dien_cu:
                                img_html_block += f'<div style="text-align: center;"><p style="font-size:12px; margin:2px 0;">Ảnh tháng trước ({thang_truoc_str})</p><img src="data:image/jpeg;base64,{b64_dien_cu}" style="max-width:220px; border:1px solid #ccc; border-radius:5px;"></div>'
                            if b64_dien_moi:
                                img_html_block += f'<div style="text-align: center;"><p style="font-size:12px; margin:2px 0; font-weight:bold;">Ảnh tháng này ({thang_hien_tai})</p><img src="data:image/jpeg;base64,{b64_dien_moi}" style="max-width:220px; border:2px solid #ff4b4b; border-radius:5px;"></div>'
                            img_html_block += '</div></div>'

                        if b64_nuoc_cu or b64_nuoc_moi:
                            img_html_block += '<div style="width: 100%; text-align: center; margin-bottom: 20px;">'
                            img_html_block += '<p style="font-size:14px; font-weight:bold; color:black; margin-bottom:5px;">💧 MINH CHỨNG CHỈ SỐ NƯỚC:</p>'
                            img_html_block += '<div style="display: flex; justify-content: center; gap: 15px;">'
                            if b64_nuoc_cu:
                                img_html_block += f'<div style="text-align: center;"><p style="font-size:12px; margin:2px 0;">Ảnh tháng trước ({thang_truoc_str})</p><img src="data:image/jpeg;base64,{b64_nuoc_cu}" style="max-width:220px; border:1px solid #ccc; border-radius:5px;"></div>'
                            if b64_nuoc_moi:
                                img_html_block += f'<div style="text-align: center;"><p style="font-size:12px; margin:2px 0; font-weight:bold;">Ảnh tháng này ({thang_hien_tai})</p><img src="data:image/jpeg;base64,{b64_nuoc_moi}" style="max-width:220px; border:2px solid #1f77b4; border-radius:5px;"></div>'
                            img_html_block += '</div></div>'

                        html_bill = f"""
<div style="border: 2px dashed #333; padding: 20px; background-color: #fff; font-family: Arial, sans-serif; color: black; max-width: 600px; margin: 0 auto;">
<h3 style="text-align: center; margin: 5px 0; font-weight: bold;">HÓA ĐƠN TIỀN NHÀ</h3>
<p style="text-align: center; margin-top: 0px; font-size: 13px; font-weight: bold; color: #d32f2f;">📅 {str_date_range}</p>
<hr style="border-top: 1px dashed #333;">
<p style="margin: 5px 0;"><b>🏠 Phòng:</b> {inv['Số Phòng']}</p>
<p style="margin: 5px 0;"><b>👤 Khách thuê:</b> {inv['Tên Khách']} ({so_nguoi_inv} người ở)</p>
<hr style="border-top: 1px dashed #333;">
<table style="width:100%; font-size: 14px; border-collapse: collapse; text-align: center;">
<tr style="border-bottom: 1px solid #aaa; font-weight: bold;">
<th style="text-align: left; padding-bottom: 5px;">Khoản mục</th>
<th style="padding-bottom: 5px;">Số cũ</th>
<th style="padding-bottom: 5px;">Số mới</th>
<th style="padding-bottom: 5px;">Sử dụng</th>
<th style="text-align: right; padding-bottom: 5px;">Thành tiền</th>
</tr>
<tr>
<td style="text-align: left; padding: 8px 0;">1. Tiền phòng</td><td>-</td><td>-</td>
<td style="font-weight: bold; color: blue;">{f'{r_days} ngày' if r_days != 30 else '1 tháng'}</td>
<td style="text-align: right;">{t_phong:,} đ</td>
</tr>
<tr>
<td style="text-align: left; padding: 8px 0;">2. Tiền Điện</td><td>{dien_cu_inv}</td><td>{dien_moi_inv}</td>
<td>{dien_dung} số</td><td style="text-align: right;">{t_dien:,} đ</td>
</tr>
<tr>
<td style="text-align: left; padding: 8px 0;">3. Tiền Nước</td><td>{nuoc_cu_inv}</td><td>{nuoc_moi_inv}</td>
<td>{nuoc_dung} khối</td><td style="text-align: right;">{t_nuoc:,} đ</td>
</tr>
<tr>
<td style="text-align: left; padding: 8px 0;">4. Tiền Rác</td><td>-</td><td>-</td>
<td style="font-weight: bold; color: blue;">{f'{so_nguoi_inv} người'}</td>
<td style="text-align: right;">{t_rac:,} đ</td>
</tr>
<tr>
<td style="text-align: left; padding: 8px 0;">5. Máy Giặt</td><td>-</td><td>-</td>
<td style="font-weight: bold; color: blue;">{f'{so_nguoi_inv} người'}</td>
<td style="text-align: right;">{t_giat:,} đ</td>
</tr>
{phat_sinh_html}
</table>
<hr style="border-top: 1px dashed #333; margin-top: 15px;">
<h3 style="text-align: right; margin-bottom: 5px; color: red; font-weight: bold;">TỔNG CỘNG: {t_tong:,} Đ</h3>
<hr style="border-top: 1px dashed #333;">
<div style="display: flex; justify-content: space-around; flex-wrap: wrap; margin-top: 15px;">
{img_html_block}
</div>
<p style="text-align: center; font-style: italic; font-size: 13px; margin-top: 25px;">Cảm ơn bạn đã thuê trọ! 🙏</p>
</div>
"""
                        st.markdown(html_bill, unsafe_allow_html=True)
                        
                        zalo_message = f"""*HÓA ĐƠN TIỀN NHÀ THÁNG {inv['Tháng']}*
🏠 Phòng: {inv['Số Phòng']}
👤 Khách thuê: {inv['Tên Khách']} ({so_nguoi_inv} người)
--------------------------------------
1. Tiền phòng: {t_phong:,} đ ({f'{r_days} ngày' if r_days != 30 else '1 tháng'})
2. Tiền Điện: {t_dien:,} đ ({dien_dung} số)
3. Tiền Nước: {t_nuoc:,} đ ({nuoc_dung} khối)
4. Tiền Rác: {t_rac:,} đ
5. Máy Giặt: {t_giat:,} đ
{f"6. Khác ({inv.get('Tên Phát Sinh')}): {int(float(inv.get('Phát Sinh', 0))):,} đ" if (inv.get('Tên Phát Sinh') != "Không" and int(float(inv.get('Phát Sinh', 0))) > 0) else ""}
--------------------------------------
💰 *TỔNG CỘNG: {t_tong:,} Đ*
_Cảm ơn bạn đã thuê trọ! 🙏_"""
                        
                        st.text_area("📋 Tin nhắn gửi Zalo nhanh:", value=zalo_message.strip(), height=200, key="zalo_box")

                        zalo_js = f"""
                        <button onclick="navigator.clipboard.writeText(decodeURIComponent('{urllib.parse.quote(zalo_message.strip())}')); alert('📋 Đã sao chép tin nhắn Zalo!');" 
                        style="width: 100%; padding: 10px; background-color: #0068FF; color: white; border: none; font-size: 14px; font-weight: bold; border-radius: 5px; cursor: pointer; margin-top: -10px;">
                        💬 BẤM VÀO ĐÂY ĐỂ COPY TIN NHẶN ZALO
                        </button>
                        """
                        st.html(zalo_js)

                        b64_html = base64.b64encode(html_bill.encode('utf-8')).decode('utf-8')
                        js_print_btn = f"""
                        <button onclick="printInvoice()" style="width: 100%; padding: 12px; background-color: #ff4b4b; color: white; border: none; font-size: 16px; font-weight: bold; border-radius: 5px; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                            🖨️ XUẤT PDF / IN HÓA ĐƠN
                        </button>
                        <script>
                            function printInvoice() {{
                                var htmlContent = decodeURIComponent(escape(atob('{b64_html}')));
                                var printWin = window.open('', '_blank', 'width=800,height=900');
                                printWin.document.open();
                                printWin.document.write('<html><head><title>In Hoa Don</title></head><body style="margin:0; padding:20px;">');
                                printWin.document.write(htmlContent);
                                printWin.document.write('<script>setTimeout(function(){{ window.print(); }}, 500);</' + 'script>');
                                printWin.document.write('</body></html>');
                                printWin.document.close();
                            }}
                        </script>
                        """
                        st.html(js_print_btn)

    # ==================== MỤC: TỔNG HỢP & THỐNG KÊ ====================
    elif user_choice == "📊 Tổng Hợp & Thống Kê":
        st.title("📊 TỔNG HỢP & THỐNG KÊ TOÀN BỘ PHÒNG")
        st.markdown("---")
        
        if not all_rows:
            st.info("ℹ️ Hiện tại chưa có dữ liệu hóa đơn nào được ghi nhận.")
        else:
            rooms_history = {}
            for r in all_rows:
                phong = r.get("Số Phòng")
                if phong:
                    if phong not in rooms_history:
                        rooms_history[phong] = []
                    rooms_history[phong].append(r)
            
            danh_sach_phong = sorted(rooms_history.keys(), key=lambda x: str(x))
            tong_doanh_thu_nha = sum(int(float(r.get("Tổng Cộng", 0) or 0)) for r in all_rows)
            
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                st.metric("🌟 TỔNG DOANH THU TÍCH LŨY TOÀN KHU TRỌ", f"{tong_doanh_thu_nha:,} VNĐ")
            with col_m2:
                st.metric("🏠 SỐ PHÒNG ĐANG QUẢN LÝ SỐ LIỆU", f"{len(danh_sach_phong)} phòng")
            
            df_all_data = pd.DataFrame(all_rows)
            csv_buffer = df_all_data.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 XUẤT TOÀN BỘ LỊCH SỬ HÓA ĐƠN RA FILE EXCEL (.CSV)",
                data=csv_buffer,
                file_name=f"lich_su_doanh_thu_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                width="stretch"
            )
                
            st.markdown("### 📋 DANH SÁCH CHI TIẾT TỪNG PHÒNG")
            st.write("*(Bấm chọn vào phòng bên dưới để bung bảng lịch sử chi tiết từng tháng như popup)*")
            
            for phong in danh_sach_phong:
                lich_su_phong = rooms_history[phong]
                lich_su_phong = sorted(lich_su_phong, key=lambda x: x.get("Tháng", ""), reverse=True)
                
                thong_tin_moi = lich_su_phong[0]
                ten_chu_ho = thong_tin_moi.get("Tên Khách", "Chưa rõ")
                tien_thang_moi = int(float(thong_tin_moi.get("Tổng Cộng", 0) or 0))
                thang_moi_nhat = thong_tin_moi.get("Tháng", "N/A")
                
                tieu_de_hien_thi = f"🏠 Phòng: {phong} | 👤 Chủ hộ: {ten_chu_ho} | 💰 Kỳ gần nhất ({thang_moi_nhat}): {tien_thang_moi:,} đ"
                
                with st.expander(tieu_de_hien_thi):
                    st.markdown(f"#### 🔍 Lịch sử hóa đơn chi tiết phòng {phong}")
                    
                    danh_sach_bang = []
                    total_phong = 0; total_dien = 0; total_nuoc = 0; total_khac = 0; total_tong_phong = 0
                    
                    for item in lich_su_phong:
                        t_phong = int(float(item.get('Tiền Phòng', 0) or 0))
                        t_dien = int(float(item.get('Tiền Điện', 0) or 0))
                        t_nuoc = int(float(item.get('Tiền Nước', 0) or 0))
                        t_rac = int(float(item.get('Tiền Rác', 0) or 0))
                        t_giat = int(float(item.get('Tiền Giặt', 0) or 0))
                        t_ps = int(float(item.get('Phát Sinh', 0) or 0))
                        t_khac = t_rac + t_giat + t_ps
                        t_tong = int(float(item.get('Tổng Cộng', 0) or 0))
                        
                        total_phong += t_phong; total_dien += t_dien; total_nuoc += t_nuoc
                        total_khac += t_khac; total_tong_phong += t_tong
                        
                        danh_sach_bang.append({
                            "Tháng / Kỳ hạn": item.get("Tháng", ""),
                            "Khách đại diện": item.get("Tên Khách", ""),
                            "Tiền Phòng lẻ/tháng": f"{t_phong:,} đ",
                            "Tiền Điện": f"{t_dien:,} đ",
                            "Tiền Nước": f"{t_nuoc:,} đ",
                            "Phí Khác (Rác/Giặt/PS)": f"{t_khac:,} đ",
                            "Tổng Thu Tháng": f"{t_tong:,} đ"
                        })
                    
                    danh_sach_bang.append({
                        "Tháng / Kỳ hạn": "🎯 TỔNG CỘNG",
                        "Khách đại diện": "---",
                        "Tiền Phòng lẻ/tháng": f"{total_phong:,} đ",
                        "Tiền Điện": f"{total_dien:,} đ",
                        "Tiền Nước": f"{total_nuoc:,} đ",
                        "Phí Khác (Rác/Giặt/PS)": f"{total_khac:,} đ",
                        "Tổng Thu Tháng": f"{total_tong_phong:,} đ"
                    })
                    
                    df_phong = pd.DataFrame(danh_sach_bang)
                    st.dataframe(df_phong, width="stretch", hide_index=True)
                    st.markdown(f"➡️ *Tổng số tiền phòng này đã đóng đóng từ trước tới nay:* **{total_tong_phong:,} đ**")
