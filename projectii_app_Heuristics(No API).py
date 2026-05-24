import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import gpxpy
import xml.etree.ElementTree as ET
import math
import datetime

# --- ฟังก์ชันคำนวณระยะทางแบบเส้นตรง (Haversine) ---
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
# เริ่มต้นหน้าเว็บ Streamlit
# ==========================================
st.set_page_config(page_title="Logistics Route Optimization Dashboard", layout="wide")
st.title("🗺️ ระบบจำลองเส้นทางขนส่งและตารางเวลา (Optimization & Dynamic ETA)")

col1, col2 = st.columns(2)
with col1:
    uploaded_file = st.file_uploader("1️⃣ อัปโหลดไฟล์สถานที่ (Excel / CSV)", type=["xlsx", "csv"])
with col2:
    route_file = st.file_uploader("2️⃣ อัปโหลดไฟล์เส้นทาง (GPX / KML) - ถ้ามี", type=["gpx", "kml"])

if uploaded_file is not None:
    try:
        # อ่านไฟล์
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file)
            
        if 'ชื่อสถานที่' in df.columns and 'Lat' in df.columns and 'Lon' in df.columns:
            
            st.subheader("📝 1. ข้อมูลสถานที่ (แก้ไขข้อมูลได้)")
            edited_df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

            # --- ส่วนเลือก Algorithm สำหรับ Optimize ---
            st.markdown("---")
            st.subheader("🧠 2. เลือกวิธีจัดเรียงเส้นทาง (Optimization)")
            algo_choice = st.radio(
                "กรุณาเลือก Algorithm ที่ต้องการให้ระบบคำนวณลำดับการเดินทาง:",
                ("1. จัดลำดับตามไฟล์ดั้งเดิม (No Optimization)", 
                 "2. Nearest Neighbor Heuristic (หาร้านที่ใกล้สุดไปเรื่อยๆ)", 
                 "3. Sweep Heuristic (กวาดเป็นวงกลมรอบจุดเริ่มต้น)")
            )

            # เรียงลำดับ Dataframe ใหม่ตาม Algorithm ที่เลือก
            is_optimized = False
            if "Nearest Neighbor" in algo_choice:
                best_route_indices = nearest_neighbor_route(edited_df)
                optimized_df = edited_df.iloc[best_route_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงเส้นทางใหม่ด้วย Nearest Neighbor สำเร็จ!")
                is_optimized = True
            elif "Sweep" in algo_choice:
                best_route_indices = sweep_route(edited_df)
                optimized_df = edited_df.iloc[best_route_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงเส้นทางใหม่ด้วย Sweep Heuristic สำเร็จ!")
                is_optimized = True
            else:
                optimized_df = edited_df.copy()
                st.info("ℹ️ ใช้ลำดับดั้งเดิมตามที่ระบุในไฟล์")

            # ตรวจสอบคอลัมน์พิเศษในไฟล์
            col_real_dist = 'ระยะห่างระหว่างแต่ละจุด (กม.)'
            col_weight = 'น้ำหนักที่ส่ง (กก.)'
            has_real_dist = col_real_dist in optimized_df.columns
            has_weight = col_weight in optimized_df.columns

            # --- ตั้งค่าตัวแปร (Parameters) ---
            st.markdown("---")
            with st.expander("⚙️ 3. ตั้งค่าพารามิเตอร์รถขนส่ง (เวลา, น้ำหนัก, น้ำมัน, คาร์บอนฟุตพริ้นท์)", expanded=False):
                st.write("**ความเร็วและน้ำหนักบรรทุก**")
                t_col1, t_col2, t_col3, t_col4 = st.columns(4)
                with t_col1:
                    empty_speed = st.number_input("ความเร็วเมื่อรถเปล่า (กม./ชม.)", value=60.0)
                with t_col2:
                    full_speed = st.number_input("ความเร็วเมื่อบรรทุกเต็ม (กม./ชม.)", value=40.0)
                with t_col3:
                    max_capacity = st.number_input("ความจุสูงสุดของรถ (กก.)", value=1000.0)
                with t_col4:
                    start_time = st.time_input("เวลาเริ่มออกเดินทาง", datetime.time(8, 0))
                
                st.write("**การดำเนินการและสิ่งแวดล้อม**")
                c_col1, c_col2, c_col3, c_col4 = st.columns(4)
                with c_col1:
                    service_time = st.number_input("เวลาลงของแต่ละจุด (นาที)", min_value=0, value=1, step=1)
                with c_col2:
                    fuel_rate = st.number_input("อัตราสิ้นเปลือง (กม./ลิตร)", value=10.0)
                with c_col3:
                    fuel_price = st.number_input("ราคาน้ำมัน (บาท/ลิตร)", value=32.50)
                with c_col4:
                    co2_rate = st.number_input("ปล่อย CO2 (kg/ลิตร)", value=2.68)

            # จัดเตรียมข้อมูลน้ำหนัก
            if has_weight:
                weight_drop_list = pd.to_numeric(optimized_df[col_weight], errors='coerce').fillna(0).tolist()
            else:
                weight_drop_list = [0.0] * len(optimized_df)
            current_weight = sum(weight_drop_list)

            # --- เริ่มคำนวณเส้นทางและเวลา ---
            current_datetime = datetime.datetime.combine(datetime.date.today(), start_time)
            schedule_data = []
            total_distance = 0.0
            total_travel_mins = 0.0
            map_route_points = [] 

            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                map_route_points.append([row['Lat'], row['Lon']])
                
                # คำนวณความเร็ว (ยิ่งเบา ยิ่งเร็ว)
                if max_capacity > 0:
                    weight_ratio = min(current_weight / max_capacity, 1.0)
                    current_speed = empty_speed - ((empty_speed - full_speed) * weight_ratio)
                else:
                    current_speed = empty_speed
                current_speed = max(current_speed, 10.0)
                
                # คำนวณระยะทาง
                if i == 0:
                    dist = 0.0
                    travel_mins = 0
                else:
                    # ถ้ารันแบบจัดเรียงใหม่ ต้องใช้เส้นตรง (เพราะลำดับไม่ตรงกับถนนจริงในตารางแล้ว)
                    # ถ้ารันแบบดั้งเดิม และมีคอลัมน์ระยะทางจริง ให้ใช้คอลัมน์นั้น
                    if not is_optimized and has_real_dist:
                        try:
                            dist = float(row[col_real_dist])
                        except:
                            dist = 0.0
                    else:
                        prev_row = optimized_df.iloc[i-1]
                        dist = calculate_distance(prev_row['Lat'], prev_row['Lon'], row['Lat'], row['Lon'])
                    
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
                    "นน. บนรถ (กก.)": f"{current_weight:.1f}" if has_weight else "-",
                    "ความเร็วที่ใช้": f"{current_speed:.1f} กม./ชม.",
                    "เวลาไปถึง (ETA)": arrival_time,
                    "เวลาออก": departure_time
                })
                
                # ลงของ
                current_weight -= weight_drop_list[i]
                if current_weight < 0: current_weight = 0

            # --- คำนวณผลลัพธ์รวม (Dashboard) ---
            total_service_mins = len(optimized_df) * service_time
            total_time_mins = total_travel_mins + total_service_mins
            hours, mins = int(total_time_mins // 60), int(total_time_mins % 60)
            
            fuel_used = total_distance / fuel_rate if fuel_rate > 0 else 0
            total_cost = fuel_used * fuel_price
            total_co2 = fuel_used * co2_rate

            st.markdown("---")
            st.subheader("📊 4. วิเคราะห์ผลลัพธ์รวม")
            if is_optimized:
                st.warning("⚠️ การคำนวณระยะทางใช้แบบ 'เส้นตรง' (Haversine) เนื่องจากมีการจัดลำดับใหม่โดย Algorithm")
            elif has_real_dist:
                st.success("✅ การคำนวณระยะทางใช้ค่าจากคอลัมน์ 'ระยะห่างระหว่างแต่ละจุด (กม.)' บนถนนจริง")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ระยะทางรวม", f"{total_distance:.2f} กม.")
            m2.metric("ต้นทุนน้ำมัน", f"฿{total_cost:.2f}")
            m3.metric("คาร์บอนฟุตพริ้นท์", f"{total_co2:.2f} kg CO2e")
            m4.metric("เวลาปฏิบัติงานรวม", f"{hours} ชม. {mins} นาที")

            st.subheader("⏱️ 5. ตารางประมาณการเวลา (ปรับตามน้ำหนักแล้ว)")
            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)

            # --- แผนที่ ---
            st.markdown("---")
            st.subheader("📍 6. แผนที่แสดงจุดจัดส่ง")
            
            if not optimized_df.empty:
                center_lat = optimized_df['Lat'].mean()
                center_lon = optimized_df['Lon'].mean()
                m = folium.Map(location=[center_lat, center_lon], zoom_start=13)

                # วาดเส้นทาง GPX/KML (ถ้ามี)
                if route_file is not None:
                    route_points = []
                    filename = route_file.name.lower()
                    try:
                        if filename.endswith('.gpx'):
                            gpx = gpxpy.parse(route_file.getvalue().decode('utf-8'))
                            for track in gpx.tracks:
                                for segment in track.segments:
                                    for point in segment.points:
                                        route_points.append((point.latitude, point.longitude))
                        elif filename.endswith('.kml'):
                            tree = ET.fromstring(route_file.getvalue())
                            for coords in tree.iterfind('.//{*}coordinates'):
                                text = coords.text.strip()
                                for pt in text.split():
                                    parts = pt.split(',')
                                    if len(parts) >= 2:
                                        route_points.append((float(parts[1]), float(parts[0])))
                        
                        if route_points:
                            folium.PolyLine(route_points, color="gray", weight=5, opacity=0.5, tooltip="เส้นทางจริงจากไฟล์").add_to(m)
                    except Exception as e:
                        st.warning(f"ไม่สามารถอ่านไฟล์เส้นทางได้: {e}")

                # วาดเส้น Algorithm (สีแดง) เชื่อมจุดต่อจุด
                folium.PolyLine(map_route_points, color="red", weight=3, opacity=0.8, tooltip="ลำดับการเดินทาง").add_to(m)

                # ปักหมุด
                schedule_df = pd.DataFrame(schedule_data)
                for i, row in optimized_df.iterrows():
                    eta_info = schedule_df.iloc[i]
                    popup_html = f"""
                    <h4 style='margin-bottom:5px;'>ลำดับ {i}: {row['ชื่อสถานที่']}</h4><hr style='margin:5px 0'>
                    <b>ถึงเวลา:</b> <span style='color:green;'>{eta_info['เวลาไปถึง (ETA)']}</span><br>
                    <b>ออกเวลา:</b> <span style='color:red;'>{eta_info['เวลาออก']}</span><br>
                    <b>ความเร็วรถขณะมาถึง:</b> <span style='color:blue;'>{eta_info['ความเร็วที่ใช้']}</span><br><br>
                    """
                    for col in optimized_df.columns:
                        if col not in ['ชื่อสถานที่', 'Lat', 'Lon']:
                            popup_html += f"<b>{col}:</b> {row[col]}<br>"
                    
                    number_icon = folium.DivIcon(html=f"""
                        <div style="background-color:#0078ff; color:white; border-radius:50%; width:30px; height:30px; 
                        display:flex; justify-content:center; align-items:center; font-weight:bold; border:2px solid white; 
                        box-shadow: 0 0 4px rgba(0,0,0,0.5); font-size:14pt;">{i}</div>
                    """, icon_anchor=(15, 15))
                    
                    folium.Marker(
                        location=[row['Lat'], row['Lon']],
                        popup=folium.Popup(popup_html, max_width=300),
                        tooltip=f"ลำดับ {i} : {row['ชื่อสถานที่']}", 
                        icon=number_icon
                    ).add_to(m)

                st_folium(m, width=1000, height=600)
            
        else:
            st.error("❌ ไฟล์ Excel ต้องมีหัวคอลัมน์ 'ชื่อสถานที่', 'Lat' และ 'Lon'")
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาด: {e}")

else:
    st.info("👆 อัปโหลดไฟล์สถานที่ (และไฟล์ GPX เส้นทาง ถ้ามี) เพื่อเริ่มต้นใช้งานระบบครับ")
