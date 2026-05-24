import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import math
import datetime
import requests

# --- ฟังก์ชันดึงราคาน้ำมันอัตโนมัติ (ปตท.) ---
@st.cache_data(ttl=3600)
def get_auto_fuel_prices():
    fallback_prices = {
        "Diesel": 32.94,
        "Gasohol 95": 36.55,
        "Gasohol 91": 36.18,
        "Gasohol E20": 34.44,
        "Benzine": 44.34
    }
    try:
        url = "https://api.chnwt.dev/thai-oil-api/latest"
        res = requests.get(url, timeout=5).json()
        ptt_data = res.get('response', {}).get('stations', {}).get('ptt', {})
        
        if not ptt_data:
            return fallback_prices
            
        fetched_prices = {}
        for name, info in ptt_data.items():
            if isinstance(info, dict) and 'price' in info and info['price']:
                try:
                    fetched_prices[name] = float(info['price'])
                except (ValueError, TypeError):
                    pass
                    
        return fetched_prices if fetched_prices else fallback_prices
    except Exception:
        return fallback_prices

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

# --- ฟังก์ชันคำนวณระยะทางแบบเส้นตรง ---
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

# --- อัลกอริทึม 3: Insertion Heuristic ---
def nearest_insertion_route(df):
    if len(df) <= 2:
        return list(range(len(df)))
    unvisited = list(range(1, len(df)))
    route = [0]
    
    first_node = min(unvisited, key=lambda x: calculate_distance(
        df.iloc[0]['Lat'], df.iloc[0]['Lon'], df.iloc[x]['Lat'], df.iloc[x]['Lon']))
    route.append(first_node)
    unvisited.remove(first_node)

    while unvisited:
        best_node = None
        min_dist_to_route = float('inf')
        for u in unvisited:
            for r in route:
                d = calculate_distance(df.iloc[u]['Lat'], df.iloc[u]['Lon'], df.iloc[r]['Lat'], df.iloc[r]['Lon'])
                if d < min_dist_to_route:
                    min_dist_to_route = d
                    best_node = u

        best_pos = 1
        min_added_dist = float('inf')
        for i in range(1, len(route) + 1):
            prev_n = route[i-1]
            next_n = route[i] if i < len(route) else route[0]
            dist_added = (calculate_distance(df.iloc[prev_n]['Lat'], df.iloc[prev_n]['Lon'], df.iloc[best_node]['Lat'], df.iloc[best_node]['Lon']) +
                          calculate_distance(df.iloc[best_node]['Lat'], df.iloc[best_node]['Lon'], df.iloc[next_n]['Lat'], df.iloc[next_n]['Lon']) -
                          calculate_distance(df.iloc[prev_n]['Lat'], df.iloc[prev_n]['Lon'], df.iloc[next_n]['Lat'], df.iloc[next_n]['Lon']))
            if dist_added < min_added_dist:
                min_added_dist = dist_added
                best_pos = i
        route.insert(best_pos, best_node)
        unvisited.remove(best_node)
    return route

# --- อัลกอริทึม 4: Saving Heuristic ---
def savings_route(df):
    if len(df) <= 2:
        return list(range(len(df)))
    n = len(df)
    savings = []
    depot_lat, depot_lon = df.iloc[0]['Lat'], df.iloc[0]['Lon']
    
    for i in range(1, n):
        for j in range(i + 1, n):
            d0i = calculate_distance(depot_lat, depot_lon, df.iloc[i]['Lat'], df.iloc[i]['Lon'])
            d0j = calculate_distance(depot_lat, depot_lon, df.iloc[j]['Lat'], df.iloc[j]['Lon'])
            dij = calculate_distance(df.iloc[i]['Lat'], df.iloc[i]['Lon'], df.iloc[j]['Lat'], df.iloc[j]['Lon'])
            s = d0i + d0j - dij
            savings.append((s, i, j))
            
    savings.sort(key=lambda x: x[0], reverse=True)
    routes = [[i] for i in range(1, n)]
    
    for s, i, j in savings:
        r_i, r_j = None, None
        for r in routes:
            if i in r: r_i = r
            if j in r: r_j = r
        if r_i != r_j and r_i is not None and r_j is not None:
            if r_i[-1] == i and r_j[0] == j:
                routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_i + r_j)
            elif r_i[0] == i and r_j[-1] == j:
                routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_j + r_i)
            elif r_i[0] == i and r_j[0] == j:
                routes.remove(r_i); routes.remove(r_j); routes.insert(0, list(reversed(r_i)) + r_j)
            elif r_i[-1] == i and r_j[-1] == j:
                routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_i + list(reversed(r_j)))
                
    final_nodes = []
    for r in routes:
        final_nodes.extend(r)
    return [0] + final_nodes

# --- อัลกอริทึม 5: 2-Opt Local Search ---
def two_opt_route(df, initial_route):
    route = initial_route.copy()
    improvement = True
    while improvement:
        improvement = False
        for i in range(1, len(route) - 2):
            for j in range(i + 1, len(route)):
                if j - i == 1: continue 
                new_route = route[:]
                new_route[i:j] = route[j-1:i-1:-1]
                
                def calc_total(r):
                    d = 0
                    for k in range(len(r)-1):
                        d += calculate_distance(df.iloc[r[k]]['Lat'], df.iloc[r[k]]['Lon'], df.iloc[r[k+1]]['Lat'], df.iloc[r[k+1]]['Lon'])
                    d += calculate_distance(df.iloc[r[-1]]['Lat'], df.iloc[r[-1]]['Lon'], df.iloc[r[0]]['Lat'], df.iloc[r[0]]['Lon'])
                    return d
                if calc_total(new_route) < calc_total(route):
                    route = new_route
                    improvement = True
    return route

# ==========================================
# เริ่มหน้าเว็บ Streamlit
# ==========================================
st.set_page_config(page_title="Milk Run Optimization & Fuel Auto", layout="wide")
st.title("🗺️ ระบบวิเคราะห์เส้นทาง Milk Run (Algorithms + อัปเดตราคาน้ำมัน)")

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
                "รูปแบบการจัดเส้นทาง (ทุกวิธีจะวิ่งลูปกลับมาคลังจุดเริ่มต้นอัตโนมัติ):",
                ("1. ลำดับตามไฟล์ดั้งเดิม (ไม่เรียงใหม่ แต่เพิ่มขากลับให้)", 
                 "2. Nearest Neighbor Heuristic (หาร้านใกล้สุดไปเรื่อยๆ)", 
                 "3. Sweep Heuristic (กวาดเป็นวงกลมรอบจุดเริ่มต้น)",
                 "4. Insertion Heuristic (แทรกจุดที่เพิ่มระยะทางรวมน้อยที่สุด)",
                 "5. Saving Heuristic (Clarke-Wright: จับคู่จุดที่ประหยัดระยะทางที่สุด)",
                 "6. Nearest Neighbor + 2-Opt Optimization (จัดเรียงแล้วแก้เส้นไขว้)")
            )

            is_optimized = False
            if "Nearest Neighbor" in algo_choice and "2-Opt" not in algo_choice:
                best_indices = nearest_neighbor_route(edited_df)
                best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงด้วย Nearest Neighbor (Closed-Loop) สำเร็จ!")
                is_optimized = True
            elif "Sweep" in algo_choice:
                best_indices = sweep_route(edited_df)
                best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงด้วย Sweep Heuristic (Closed-Loop) สำเร็จ!")
                is_optimized = True
            elif "Insertion" in algo_choice:
                best_indices = nearest_insertion_route(edited_df)
                best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงด้วย Insertion Heuristic (Closed-Loop) สำเร็จ!")
                is_optimized = True
            elif "Saving" in algo_choice:
                best_indices = savings_route(edited_df)
                best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงด้วย Saving Heuristic (Closed-Loop) สำเร็จ!")
                is_optimized = True
            elif "2-Opt" in algo_choice:
                nn_indices = nearest_neighbor_route(edited_df)
                best_indices = two_opt_route(edited_df, nn_indices)
                best_indices.append(0); optimized_df = edited_df.iloc[best_indices].reset_index(drop=True)
                st.success("✅ จัดเรียงด้วย Nearest Neighbor + 2-Opt Optimization สำเร็จ!")
                is_optimized = True
            else:
                optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)
                st.info("ℹ️ ใช้ลำดับดั้งเดิมตามที่ระบุในไฟล์ (เพิ่มขากลับจุดเริ่มต้นให้แล้ว)")

            road_geometry, road_distances = get_osrm_route(optimized_df)

            col_weight = 'น้ำหนักที่ส่ง (กก.)'
            col_real_dist = 'ระยะห่างระหว่างแต่ละจุด (กม.)'
            has_weight = col_weight in optimized_df.columns
            has_real_dist = col_real_dist in optimized_df.columns

            st.markdown("---")
            with st.expander("⚙️ 3. ตั้งค่าพารามิเตอร์รถขนส่ง", expanded=True):
                t_col1, t_col2, t_col3, t_col4 = st.columns(4)
                with t_col1: empty_speed = st.number_input("ความเร็วรถเปล่า (กม./ชม.)", value=60.0)
                with t_col2: full_speed = st.number_input("ความเร็วบรรทุกเต็ม (กม./ชม.)", value=40.0)
                with t_col3: max_capacity = st.number_input("ความจุรถสูงสุด (กก.)", value=1000.0)
                with t_col4: start_time = st.time_input("เวลาออกเดินทาง", datetime.time(11, 0))
                
                c_col1, c_col2, c_col3, c_col4 = st.columns(4)
                with c_col1: service_time = st.number_input("เวลาลงของ/จุด (นาที)", value=3)
                with c_col2: fuel_rate = st.number_input("สิ้นเปลือง (กม./ลิตร)", value=10.0)
                
                # --- เมนูดึงราคาน้ำมันอัตโนมัติ ---
                fuel_prices_dict = get_auto_fuel_prices()
                fuel_options = list(fuel_prices_dict.keys())
                
                # ค้นหาคำว่า "Diesel" หรือ "ดีเซล" แบบครอบคลุม เพื่อล็อคเป็น Default
                default_index = 0
                for idx, option in enumerate(fuel_options):
                    if "diesel" in option.lower() or "ดีเซล" in option:
                        default_index = idx
                        break
                
                with c_col3: 
                    selected_fuel = st.selectbox("ชนิดน้ำมัน (ราคา ปตท. ล่าสุด)", fuel_options, index=default_index)
                with c_col4: 
                    fuel_price = st.number_input(f"ราคา {selected_fuel} (บาท/ลิตร)", value=float(fuel_prices_dict.get(selected_fuel, 32.50)))

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
                    if not is_optimized and has_real_dist:
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
            st.subheader("📊 4. สรุปผลลัพธ์การเดินรถรวม")
            if is_optimized and road_distances:
                st.success("✅ ระยะทางคำนวณตามโครงข่ายถนนจริง (OSRM) จากลำดับเส้นทางที่จัดใหม่")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("ระยะทางรวมทั้งสิ้น", f"{total_distance:.2f} กม.")
            m2.metric(f"ต้นทุนน้ำมัน ({selected_fuel})", f"฿{(total_distance/fuel_rate * fuel_price) if fuel_rate > 0 else 0:.2f}")
            m3.metric("เวลาที่ใช้อยู่บนถนน", f"{int(total_travel_mins//60)} ชม. {int(total_travel_mins%60)} น.")
            m4.metric("เวลาจบงาน (ถึงจุดเริ่มต้น)", f"{int(total_time_mins//60)} ชม. {int(total_time_mins%60)} น.")

            st.dataframe(pd.DataFrame(schedule_data), use_container_width=True)

            st.markdown("---")
            st.subheader("📍 5. แผนที่เส้นทางเดินรถ Closed-Loop")
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
    st.info("👆 อัปโหลดไฟล์สถานที่เพื่อเริ่มต้นและเปรียบเทียบอัลกอริทึม")
