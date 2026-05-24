import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import math
import datetime
import requests

# --- ฟังก์ชันดึงราคาน้ำมันอัตโนมัติ (ดีเซล ปตท.) ---
@st.cache_data(ttl=3600) # โหลดข้อมูลใหม่ทุก 1 ชั่วโมง เพื่อไม่ให้เว็บอืด
def get_auto_fuel_price():
    try:
        url = "https://api.chnwt.dev/thai-oil-api/latest"
        res = requests.get(url, timeout=5).json()
        price = res['response']['stations']['ptt']['Diesel']['price']
        return float(price)
    except Exception:
        return 32.50 # ราคาสำรองหากดึงข้อมูลไม่ได้

# --- ฟังก์ชันดึงเส้นทางถนนจริงจาก OSRM ---
def get_osrm_route(df):
    try:
        coords = ";".join([f"{row['Lon']},{row['Lat']}" for _, row in df.iterrows()])
        url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
        
        response = requests.get(url).json()
        if response.get("code") == "Ok":
            route = response["routes"][0]
            geometry = [[coord[1], coord[0]] for coord in route["geometry"]["coordinates"]]
            leg_distances = [leg["distance"] / 1000.0 for leg in route["legs"]]
            return geometry, leg_distances
    except Exception as e:
        st.warning(f"ไม่สามารถเชื่อมต่อระบบถนน OSRM ได้ (กำลังสลับไปใช้ระยะทางเส้นตรงแทน) Error: {e}")
    return None, None

# --- ฟังก์ชันคำนวณระยะทางแบบเส้นตรง (สำรอง) ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0 
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


# ==========================================
# เริ่มหน้าเว็บ Streamlit
# ==========================================
st.set_page_config(page_title="Milk Run Routing (No API)", layout="wide")
st.title("🗺️ ระบบจำลองเส้นทาง Milk Run (ลำดับตามไฟล์)")

uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            st.subheader("📝 1. ข้อมูลสถานที่ต้นทางและลูกค้า")
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            # บังคับต่อท้ายด้วยจุดเริ่มต้นเสมอ (Closed-Loop) โดยไม่ต้องเลือก Algorithm
            optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)
            st.success("✅ ระบบใช้ลำดับการวิ่งตามไฟล์ของคุณ และได้เพิ่มขากลับเข้าจุดเริ่มต้น (Closed-Loop) ให้อัตโนมัติแล้ว")

            road_geometry, road_distances = get_osrm_route(optimized_df)

            col_weight = 'น้ำหนักที่ส่ง (กก.)'
            col_real_dist = 'ระยะห่างระหว่างแต่ละจุด (กม.)'
            has_weight = col_weight in optimized_df.columns
            has_real_dist = col_real_dist in optimized_df.columns

            st.markdown("---")
            with st.expander("⚙️ 2. ตั้งค่าพารามิเตอร์รถขนส่ง", expanded=True):
                t_col1, t_col2, t_col3, t_col4 = st.columns(4)
                with t_col1: empty_speed = st.number_input("ความเร็วรถเปล่า (กม./ชม.)", value=60.0)
                with t_col2: full_speed = st.number_input("ความเร็วบรรทุกเต็ม (กม./ชม.)", value=40.0)
                with t_col3: max_capacity = st.number_input("ความจุรถสูงสุด (กก.)", value=1000.0)
                # ตั้งค่า Default เป็น 11:00
                with t_col4: start_time = st.time_input("เวลาออกเดินทาง", datetime.time(11, 0))
                
                c_col1, c_col2, c_col3 = st.columns(3)
                # ตั้งค่าเวลาลงของ Default เป็น 3 นาที
                with c_col1: service_time = st.number_input("เวลาลงของ/จุด (นาที)", value=3)
                with c_col2: fuel_rate = st.number_input("สิ้นเปลือง (กม./ลิตร)", value=10.0)
                
                # ดึงราคาน้ำมันออโต้มาเป็นค่าเริ่มต้น
                today_fuel_price = get_auto_fuel_price()
                with c_col3: fuel_price = st.number_input("ราคาน้ำมัน ดีเซล (บาท/ลิตร) อัปเดตล่าสุด", value=today_fuel_price)

            if has_weight:
                weight_list = pd.to_numeric(optimized_df[col_weight], errors='coerce').fillna(0).tolist()
                weight_list[-1] = 0.0
            else:
                weight_list = [0.0] * len(optimized_df)
            current_weight = sum(weight_list)

            current_datetime = datetime.datetime.combine(datetime.date.today(), start_time)
            schedule_data = []
            total_distance = 0.0
            total_travel_mins = 0.0
            map_markers = []

            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                map_markers.append([row['Lat'], row['Lon']])
                
                if max_capacity > 0:
                    weight_ratio = min(current_weight / max_capacity, 1.0)
                    current_speed = empty_speed - ((empty_speed - full_speed) * weight_ratio)
                else: current_speed = empty_speed
                current_speed = max(current_speed, 10.0)
                
                if i == 0:
                    dist = 0.0
                    travel_mins = 0
                else:
                    if has_real_dist:
                        try: dist = float(row[col_real_dist])
                        except: dist = 0.0
                    elif road_distances:
                        dist = road_distances[i-1] 
                    else:
                        dist = calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon'])
                    
                    travel_mins = (dist / current_speed) * 60
                
                total_distance += dist
                total_travel_mins += travel_mins
                
                current_datetime += datetime.timedelta(minutes=travel_mins)
                arrival_time = current_datetime.strftime("%H:%M:%S")
                
                if i == len(optimized_df) - 1: departure_time = "-"
                else:
                    current_datetime += datetime.timedelta(minutes=service_time)
                    departure_time = current_datetime.strftime("%H:%M:%S")
                
                display_name = row['ชื่อสถานที่']
                if i == len(optimized_df) - 1: display_name = f"🔄 กลับสู่: {row['ชื่อสถานที่']}"

                schedule_data.append({
                    "ลำดับคิว": i,
                    "ชื่อสถานที่": display_name,
                    "ระยะทางจากจุดก่อนหน้า (กม.)": f"{dist:.2f}",
                    "นน. คงเหลือบนรถ (กก.)": f"{current_weight:.1f}" if has_weight else "-",
                    "ความเร็วช่วงนี้": f"{current_speed:.1f} กม./ชม.",
                    "เวลาไปถึง (ETA)": arrival_time,
                    "เวลาที่รถออกจากจุด": departure_time
                })
                current_weight -= weight_list[i]
                if current_weight < 0: current_weight = 0

            total_time_mins = total_travel_mins + ((len(optimized_df) - 1) * service_time)
            
            st.markdown("---")
            st.subheader("📊 3. สรุปผลลัพธ์การเดินรถรวม")
            if road_distances:
                st.info("ℹ️ ระยะทางคำนวณตามโครงข่ายถนนจริง (OSRM) จากลำดับการจัดส่งของคุณ")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ระยะทางรวมทั้งสิ้น", f"{total_distance:.2f} กม.")
            m2.metric("ต้นทุนน้ำมันรวม", f"฿{(total_distance/fuel_rate * fuel_price) if fuel_rate > 0 else 0:.2f}")
            m3.metric("เวลาที่ใช้อยู่บนถนน", f"{int(total_travel_mins//60)} ชม. {int(total_travel_mins%60)} น.")
            m4.metric("เวลาจบงาน (ถึงจุดเริ่มต้น)", f"{int(total_time_mins//60)} ชม. {int(total_time_mins%60)} น.")

            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)

            st.markdown("---")
            st.subheader("📍 4. แผนที่เส้นทางเดินรถ Closed-Loop")
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)

            if road_geometry:
                folium.PolyLine(road_geometry, color="blue", weight=5, opacity=0.8, tooltip="เส้นทางแบบ Closed-Loop").add_to(m)
            else:
                folium.PolyLine(map_markers, color="red", weight=3, opacity=0.8, dash_array="5").add_to(m)

            for i in range(len(optimized_df) - 1):
                row = optimized_df.iloc[i]
                html = f"<b>ลำดับคิว {i}: {row['ชื่อสถานที่']}</b><br>เวลาถึง: {schedule_data[i]['เวลาไปถึง (ETA)']}"
                color_bg = "#ff2200" if i == 0 else "#0078ff"
                label_text = "คลัง" if i == 0 else str(i)
                
                icon = folium.DivIcon(html=f"""<div style="background-color:{color_bg}; color:white; border-radius:50%; width:32px; height:32px; display:flex; justify-content:center; align-items:center; font-weight:bold; border:2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);">{label_text}</div>""", icon_anchor=(16, 16))
                folium.Marker(location=[row['Lat'], row['Lon']], popup=html, icon=icon).add_to(m)

            st_folium(m, width=1000, height=600)
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")
else:
    st.info("👆 อัปโหลดไฟล์สถานที่เพื่อดูการประมวลผลเส้นทาง")
