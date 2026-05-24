import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import math
import datetime
import requests # เพิ่มเข้ามาใหม่สำหรับดึงข้อมูลเส้นทางถนน

# --- ฟังก์ชันดึงเส้นทางถนนจริงจาก OSRM (ฟรี ไม่ต้องใช้ API Key) ---
def get_osrm_route(df):
    try:
        # นำพิกัดทั้งหมดมาเรียงต่อกันเป็น String
        coords = ";".join([f"{row['Lon']},{row['Lat']}" for _, row in df.iterrows()])
        url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
        
        response = requests.get(url).json()
        if response.get("code") == "Ok":
            route = response["routes"][0]
            # สลับ [Lon, Lat] กลับมาเป็น [Lat, Lon] สำหรับ Folium
            geometry = [[coord[1], coord[0]] for coord in route["geometry"]["coordinates"]]
            # ดึงระยะทางของแต่ละช่วงถนน (แปลงจากเมตรเป็นกิโลเมตร)
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

# --- อัลกอริทึม 1: Nearest Neighbor Heuristic ---
def nearest_neighbor_route(df):
    unvisited = list(range(1, len(df)))
    route = [0]
    current = 0
    while unvisited:
        next_node = min(unvisited, key=lambda x: calculate_distance(
            df.iloc[current]['Lat'], df.iloc[current]['Lon'], 
            df.iloc[x]['Lat'], df.iloc[x]['Lon']
        ))
        route.append(next_node)
        current = next_node
        unvisited.remove(next_node)
    return route

# --- อัลกอริทึม 2: Sweep Heuristic ---
def sweep_route(df):
    depot_lat, depot_lon = df.iloc[0]['Lat'], df.iloc[0]['Lon']
    angles = []
    for i in range(1, len(df)):
        lat, lon = df.iloc[i]['Lat'], df.iloc[i]['Lon']
        angle = math.atan2(lat - depot_lat, lon - depot_lon)
        angles.append((i, angle))
    angles.sort(key=lambda x: x[1])
    return [0] + [x[0] for x in angles]

# ==========================================
# เริ่มหน้าเว็บ
# ==========================================
st.set_page_config(page_title="Logistics Routing Dashboard", layout="wide")
st.title("🗺️ ระบบจัดเส้นทางบนถนนจริง (OSRM & Heuristics)")

uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file is not None:
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            
            st.subheader("📝 1. ข้อมูลสถานที่")
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            st.markdown("---")
            st.subheader("🧠 2. เลือกวิธีจัดเรียงเส้นทาง")
            algo_choice = st.radio(
                "รูปแบบการวิ่งรถ:",
                ("1. ลำดับตามไฟล์ดั้งเดิม", 
                 "2. Nearest Neighbor Heuristic (หาร้านที่ใกล้สุดไปเรื่อยๆ)", 
                 "3. Sweep Heuristic (กวาดเป็นวงกลมรอบจุด)")
            )

            if "Nearest Neighbor" in algo_choice:
                best_indices = nearest_neighbor_route(edited_df)
                optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            elif "Sweep" in algo_choice:
                best_indices = sweep_route(edited_df)
                optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
            else:
                optimized_df = edited_df.copy()

            # --- ดึงข้อมูลถนนจาก OSRM ---
            road_geometry, road_distances = get_osrm_route(optimized_df)

            col_weight = 'น้ำหนักที่ส่ง (กก.)'
            has_weight = col_weight in optimized_df.columns

            st.markdown("---")
            with st.expander("⚙️ 3. ตั้งค่าพารามิเตอร์", expanded=False):
                t_col1, t_col2, t_col3, t_col4 = st.columns(4)
                with t_col1:
                    empty_speed = st.number_input("ความเร็วรถเปล่า (กม./ชม.)", value=60.0)
                with t_col2:
                    full_speed = st.number_input("ความเร็วบรรทุกเต็ม (กม./ชม.)", value=40.0)
                with t_col3:
                    max_capacity = st.number_input("ความจุรถ (กก.)", value=1000.0)
                with t_col4:
                    start_time = st.time_input("เวลาออกเดินทาง", datetime.time(8, 0))
                
                c_col1, c_col2, c_col3 = st.columns(3)
                with c_col1:
                    service_time = st.number_input("เวลาลงของ/จุด (นาที)", value=1)
                with c_col2:
                    fuel_rate = st.number_input("สิ้นเปลือง (กม./ลิตร)", value=10.0)
                with c_col3:
                    fuel_price = st.number_input("ราคาน้ำมัน (บาท/ลิตร)", value=32.50)

            if has_weight:
                weight_list = pd.to_numeric(optimized_df[col_weight], errors='coerce').fillna(0).tolist()
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
                else:
                    current_speed = empty_speed
                current_speed = max(current_speed, 10.0)
                
                if i == 0:
                    dist = 0.0
                    travel_mins = 0
                else:
                    # เลือกระหว่างระยะถนนจริง (ถ้ามี) หรือเส้นตรง
                    if road_distances:
                        dist = road_distances[i-1] # ระยะทางจากจุด i-1 ถึง i
                    else:
                        dist = calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon'])
                    
                    travel_mins = (dist / current_speed) * 60
                
                total_distance += dist
                total_travel_mins += travel_mins
                
                current_datetime += datetime.timedelta(minutes=travel_mins)
                arrival_time = current_datetime.strftime("%H:%M:%S")
                current_datetime += datetime.timedelta(minutes=service_time)
                departure_time = current_datetime.strftime("%H:%M:%S")
                
                schedule_data.append({
                    "ลำดับ": i,
                    "ชื่อสถานที่": row['ชื่อสถานที่'],
                    "ระยะห่าง (กม.)": f"{dist:.2f}",
                    "ความเร็ว": f"{current_speed:.1f} กม./ชม.",
                    "เวลาไปถึง": arrival_time,
                    "เวลาออก": departure_time
                })
                
                current_weight -= weight_list[i]
                if current_weight < 0: current_weight = 0

            # --- วิเคราะห์ผลลัพธ์ ---
            total_time_mins = total_travel_mins + (len(optimized_df) * service_time)
            
            st.markdown("---")
            st.subheader("📊 4. สรุปผลลัพธ์")
            if road_distances:
                st.success("✅ คำนวณระยะทางและวาดเส้นตาม **ถนนจริง** สำเร็จ!")
            else:
                st.warning("⚠️ คำนวณระยะทางแบบเส้นตรง (Haversine)")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ระยะทางรวม", f"{total_distance:.2f} กม.")
            m2.metric("ต้นทุนน้ำมัน", f"฿{(total_distance/fuel_rate * fuel_price) if fuel_rate > 0 else 0:.2f}")
            m3.metric("เวลาเดินทางบนถนน", f"{int(total_travel_mins//60)} ชม. {int(total_travel_mins%60)} น.")
            m4.metric("เวลาปฏิบัติงานรวม", f"{int(total_time_mins//60)} ชม. {int(total_time_mins%60)} น.")

            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)

            # --- แผนที่ ---
            st.markdown("---")
            st.subheader("📍 5. แผนที่เส้นทางถนน")
            
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)

            # วาดเส้นทาง (ถนนจริง หรือ เส้นตรง)
            if road_geometry:
                folium.PolyLine(road_geometry, color="blue", weight=5, opacity=0.8, tooltip="เส้นทางถนนจริง").add_to(m)
            else:
                folium.PolyLine(map_markers, color="red", weight=3, opacity=0.8, dash_array="5", tooltip="เส้นตรง (สำรอง)").add_to(m)

            # ปักหมุด
            for i, row in optimized_df.iterrows():
                html = f"<b>ลำดับ {i}: {row['ชื่อสถานที่']}</b><br>ถึงเวลา: {schedule_data[i]['เวลาไปถึง']}"
                icon = folium.DivIcon(html=f"""<div style="background-color:#0078ff; color:white; border-radius:50%; width:30px; height:30px; display:flex; justify-content:center; align-items:center; font-weight:bold; border:2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);">{i}</div>""", icon_anchor=(15, 15))
                folium.Marker(location=[row['Lat'], row['Lon']], popup=html, icon=icon).add_to(m)

            st_folium(m, width=1000, height=600)
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")
