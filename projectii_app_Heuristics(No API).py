import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import math
import datetime
import requests

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
st.set_page_config(page_title="Closed-Loop Milk Run Dashboard", layout="wide")
st.title("🗺️ ระบบจัดการเส้นทาง Milk Run (กลับจุดเริ่มต้นอัตโนมัติ)")

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

            st.markdown("---")
            st.subheader("🧠 2. เลือกวิธีจัดเรียงเส้นทาง (Optimization)")
            algo_choice = st.radio(
                "รูปแบบการจัดเส้นทาง (ทุกวิธีจะวิ่งกลับมาสิ้นสุดที่จุดแรกสุดเสมอ):",
                ("1. ลำดับตามไฟล์ดั้งเดิม (บวกลูปกลับจุดเริ่มต้น)", 
                 "2. Nearest Neighbor Heuristic (หาร้านที่ใกล้สุดไปเรื่อยๆ -> กลับจุดเริ่ม)", 
                 "3. Sweep Heuristic (กวาดเป็นวงกลมรอบจุด -> กลับจุดเริ่ม)")
            )

            # ทำการจัดลำดับและ "เพิ่มจุดกลับเริ่มต้นปิดท้าย" เพื่อทำ Closed-loop
            if "Nearest Neighbor" in algo_choice:
                best_indices = nearest_neighbor_route(edited_df)
                best_indices.append(0) # บังคับวนกลับมาจุดแรกสุด
                optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงเส้นทางใหม่ด้วย Nearest Neighbor (Closed-Loop) สำเร็จ!")
            elif "Sweep" in algo_choice:
                best_indices = sweep_route(edited_df)
                best_indices.append(0) # บังคับวนกลับมาจุดแรกสุด
                optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงเส้นทางใหม่ด้วย Sweep Heuristic (Closed-Loop) สำเร็จ!")
            else:
                # กรณีใช้ลำดับเดิมในไฟล์ แต่ต้องดึงบรรทัดแรกมาแปะปิดท้ายขากลับ
                optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)
                st.info("ℹ️ ใช้ลำดับดั้งเดิมตามที่ระบุในไฟล์ (เพิ่มขากลับจุดเริ่มต้นให้แล้ว)")

            # --- ดึงข้อมูลถนนจาก OSRM ---
            road_geometry, road_distances = get_osrm_route(optimized_df)

            col_weight = 'น้ำหนักที่ส่ง (กก.)'
            has_weight = col_weight in optimized_df.columns

            st.markdown("---")
            with st.expander("⚙️ 3. ตั้งค่าพารามิเตอร์รถขนส่ง", expanded=False):
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

            # จัดเตรียมข้อมูลน้ำหนัก
            if has_weight:
                # จุดสุดท้ายที่กลับเข้าคลังจะไม่มีการลงน้ำหนักเพิ่ม (เป็น 0)
                weight_list = pd.to_numeric(optimized_df[col_weight], errors='coerce').fillna(0).tolist()
                # บรรทัดสุดท้ายที่เป็นขากลับคลัง ค่าน้ำหนักลงของต้องเป็น 0 เสมอ
                weight_list[-1] = 0.0
            else:
                weight_list = [0.0] * len(optimized_df)
            
            # น้ำหนักรวมที่เริ่มบรรทุกออกจากจุดสตาร์ท
            current_weight = sum(weight_list)

            current_datetime = datetime.datetime.combine(datetime.date.today(), start_time)
            schedule_data = []
            total_distance = 0.0
            total_travel_mins = 0.0
            map_markers = []

            for i in range(len(optimized_df)):
                row = optimized_df.iloc[i]
                map_markers.append([row['Lat'], row['Lon']])
                
                # คำนวณความเร็วแปรผันตามน้ำหนัก
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
                    if road_distances:
                        dist = road_distances[i-1] 
                    else:
                        dist = calculate_distance(optimized_df.iloc[i-1]['Lat'], optimized_df.iloc[i-1]['Lon'], row['Lat'], row['Lon'])
                    
                    travel_mins = (dist / current_speed) * 60
                
                total_distance += dist
                total_travel_mins += travel_mins
                
                current_datetime += datetime.timedelta(minutes=travel_mins)
                arrival_time = current_datetime.strftime("%H:%M:%S")
                
                # ถ้าเป็นจุดสุดท้าย (กลับถึงคลังแล้ว) ไม่ต้องบวกเวลากระจายของเพิ่ม
                if i == len(optimized_df) - 1:
                    departure_time = "-"
                else:
                    current_datetime += datetime.timedelta(minutes=service_time)
                    departure_time = current_datetime.strftime("%H:%M:%S")
                
                # กำหนดชื่อเรียกเพื่อไม่ให้สับสนในตารางเวลา
                display_name = row['ชื่อสถานที่']
                if i == len(optimized_df) - 1:
                    display_name = f"🔄 กลับสู่: {row['ชื่อสถานที่']}"

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

            # --- วิเคราะห์ผลลัพธ์ ---
            # เวลาทั้งหมด = เวลาวิ่งรถ + เวลารอลงของ (ไม่รวมจุดสุดท้าย)
            total_time_mins = total_travel_mins + ((len(optimized_df) - 1) * service_time)
            
            st.markdown("---")
            st.subheader("📊 4. สรุปผลลัพธ์การเดินรถรวม (รวมขากลับคลังแล้ว)")
            if road_distances:
                st.success("✅ เส้นทางถนนจริงลากวนลูปกลับมาที่คลังสิ้นสุดโครงการเรียบร้อย")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ระยะทางรวมทั้งสิ้น", f"{total_distance:.2f} กม.")
            m2.metric("ต้นทุนน้ำมันรวม", f"฿{(total_distance/fuel_rate * fuel_price) if fuel_rate > 0 else 0:.2f}")
            m3.metric("เวลาที่ใช้อยู่บนถนน", f"{int(total_travel_mins//60)} ชม. {int(total_travel_mins%60)} น.")
            m4.metric("เวลาจบงาน (ถึงจุดเริ่มต้น)", f"{int(total_time_mins//60)} ชม. {int(total_time_mins%60)} น.")

            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)

            # --- แผนที่ ---
            st.markdown("---")
            st.subheader("📍 5. แผนที่เส้นทางเดินรถ Closed-Loop")
            
            m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)

            # วาดเส้นทางถนน OSRM วนกลับจุดเริ่มต้น
            if road_geometry:
                folium.PolyLine(road_geometry, color="blue", weight=5, opacity=0.8, tooltip="เส้นทางแบบ Closed-Loop").add_to(m)
            else:
                folium.PolyLine(map_markers, color="red", weight=3, opacity=0.8, dash_array="5").add_to(m)

            # ปักหมุด (จุดสุดท้ายที่เป็นขากลับคลัง ไม่จำเป็นต้องปักซ้ำเพื่อไม่ให้หมุดซ้อนกัน)
            for i in range(len(optimized_df) - 1):
                row = optimized_df.iloc[i]
                html = f"<b>ลำดับคิว {i}: {row['ชื่อสถานที่']}</b><br>เวลาถึง: {schedule_data[i]['เวลาไปถึง']}"
                
                # หากเป็นคิวที่ 0 ให้เด่นขึ้นมาหน่อยว่าเป็น Depot
                color_bg = "#ff2200" if i == 0 else "#0078ff"
                label_text = "คลัง" if i == 0 else str(i)
                
                icon = folium.DivIcon(html=f"""<div style="background-color:{color_bg}; color:white; border-radius:50%; width:32px; height:32px; display:flex; justify-content:center; align-items:center; font-weight:bold; border:2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);">{label_text}</div>""", icon_anchor=(16, 16))
                folium.Marker(location=[row['Lat'], row['Lon']], popup=html, icon=icon).add_to(m)

            st_folium(m, width=1000, height=600)
            
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการประมวลผล: {e}")

else:
    st.info("👆 อัปโหลดไฟล์สถานที่เพื่อดูการประมวลผลและเส้นทางแบบวนกลับจุดเริ่มต้น")
