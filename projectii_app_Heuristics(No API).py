import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests
import re
import xml.etree.ElementTree as ET

# --- ฟังก์ชันอ่านพิกัดจาก KML ---
def extract_coords_from_kml(kml_file):
    try:
        tree = ET.parse(kml_file)
        root = tree.getroot()
        ns = {'kml': 'http://www.opengis.net/kml/2.2'}
        coord_element = root.find('.//kml:LineString/kml:coordinates', ns)
        if coord_element is not None:
            coords_str = coord_element.text.strip()
            coords_list = []
            for pair in coords_str.split():
                parts = pair.split(',')
                lon, lat = float(parts[0]), float(parts[1])
                coords_list.append([lat, lon])
            return coords_list
    except Exception as e:
        st.error(f"ไม่สามารถอ่านไฟล์ KML ได้: {e}")
    return None

# --- ฟังก์ชันสร้างไฟล์ KML/GPX ---
def create_kml(df, geometry):
    kml_header = '<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n<name>Milk Run Route</name>\n'
    kml_footer = '</Document>\n</kml>'
    kml_body = ""
    for i in range(len(df) - 1):
        row = df.iloc[i]
        kml_body += f"<Placemark><name>{i}: {row['ชื่อสถานที่']}</name><Point><coordinates>{row['Lon']},{row['Lat']},0</coordinates></Point></Placemark>\n"
    coords_str = " ".join([f"{lon},{lat},0" for lat, lon in geometry])
    kml_body += f"<Placemark><name>Route Path</name><LineString><coordinates>{coords_str}</coordinates></LineString></Placemark>\n"
    return kml_header + kml_body + kml_footer

def create_gpx(df, geometry):
    gpx = '<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="MilkRunApp">\n'
    for i in range(len(df) - 1):
        row = df.iloc[i]
        gpx += f'<wpt lat="{row["Lat"]}" lon="{row["Lon"]}"><name>{i}: {row["ชื่อสถานที่"]}</name></wpt>\n'
    gpx += '<trk><name>Milk Run Route Path</name><trkseg>\n'
    for lat, lon in geometry:
        gpx += f'<trkpt lat="{lat}" lon="{lon}"></trkpt>\n'
    gpx += '</trkseg></trk>\n</gpx>'
    return gpx

# --- ฟังก์ชันดึงราคาน้ำมัน ---
@st.cache_data(ttl=3600)
def get_auto_fuel_prices():
    fallback = {"Diesel": 32.94, "Gasohol 95": 36.55}
    try:
        res = requests.get("https://api.chnwt.dev/thai-oil-api/latest", timeout=5).json()
        ptt = res.get('response', {}).get('stations', {}).get('ptt', {})
        if not ptt: return fallback
        return {name: float(info['price']) for name, info in ptt.items() if info.get('price')}
    except: return fallback

# --- คำนวณระยะทางเส้นตรง ---
def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371.0 
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

# --- Algorithms ---
def nearest_neighbor_route(df):
    unvisited = list(range(1, len(df))); route = [0]; current = 0
    while unvisited:
        next_n = min(unvisited, key=lambda x: calculate_distance(df.iloc[current]['Lat'], df.iloc[current]['Lon'], df.iloc[x]['Lat'], df.iloc[x]['Lon']))
        route.append(next_n); current = next_n; unvisited.remove(next_n)
    return route

def sweep_route(df):
    depot_lat, depot_lon = df.iloc[0]['Lat'], df.iloc[0]['Lon']
    angles = [(i, math.atan2(df.iloc[i]['Lat']-depot_lat, df.iloc[i]['Lon']-depot_lon)) for i in range(1, len(df))]
    angles.sort(key=lambda x: x[1])
    return [0] + [x[0] for x in angles]

def nearest_insertion_route(df):
    if len(df) <= 2: return list(range(len(df)))
    unvisited = list(range(1, len(df))); route = [0]
    first = min(unvisited, key=lambda x: calculate_distance(df.iloc[0]['Lat'], df.iloc[0]['Lon'], df.iloc[x]['Lat'], df.iloc[x]['Lon']))
    route.append(first); unvisited.remove(first)
    while unvisited:
        best_node = None; min_dist = float('inf')
        for u in unvisited:
            for r in route:
                d = calculate_distance(df.iloc[u]['Lat'], df.iloc[u]['Lon'], df.iloc[r]['Lat'], df.iloc[r]['Lon'])
                if d < min_dist: min_dist = d; best_node = u
        best_pos = 1; min_added = float('inf')
        for i in range(1, len(route) + 1):
            prev_n, next_n = route[i-1], route[i] if i < len(route) else route[0]
            dist_added = calculate_distance(df.iloc[prev_n]['Lat'], df.iloc[prev_n]['Lon'], df.iloc[best_node]['Lat'], df.iloc[best_node]['Lon']) + \
                         calculate_distance(df.iloc[best_node]['Lat'], df.iloc[best_node]['Lon'], df.iloc[next_n]['Lat'], df.iloc[next_n]['Lon']) - \
                         calculate_distance(df.iloc[prev_n]['Lat'], df.iloc[prev_n]['Lon'], df.iloc[next_n]['Lat'], df.iloc[next_n]['Lon'])
            if dist_added < min_added: min_added = dist_added; best_pos = i
        route.insert(best_pos, best_node); unvisited.remove(best_node)
    return route

def savings_route(df):
    if len(df) <= 2: return list(range(len(df)))
    n = len(df); savings = []; depot_lat, depot_lon = df.iloc[0]['Lat'], df.iloc[0]['Lon']
    for i in range(1, n):
        for j in range(i+1, n):
            s = calculate_distance(depot_lat, depot_lon, df.iloc[i]['Lat'], df.iloc[i]['Lon']) + calculate_distance(depot_lat, depot_lon, df.iloc[j]['Lat'], df.iloc[j]['Lon']) - calculate_distance(df.iloc[i]['Lat'], df.iloc[i]['Lon'], df.iloc[j]['Lat'], df.iloc[j]['Lon'])
            savings.append((s, i, j))
    savings.sort(key=lambda x: x[0], reverse=True); routes = [[i] for i in range(1, n)]
    for s, i, j in savings:
        r_i, r_j = None, None
        for r in routes:
            if i in r: r_i = r
            if j in r: r_j = r
        if r_i != r_j and r_i and r_j:
            if r_i[-1] == i and r_j[0] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_i + r_j)
            elif r_i[0] == i and r_j[-1] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_j + r_i)
            elif r_i[0] == i and r_j[0] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, list(reversed(r_i)) + r_j)
            elif r_i[-1] == i and r_j[-1] == j: routes.remove(r_i); routes.remove(r_j); routes.insert(0, r_i + list(reversed(r_j)))
    final = []; [final.extend(r) for r in routes]
    return [0] + final

# --- UI Main ---
st.set_page_config(page_title="Milk Run Logistics", layout="wide")
st.title("🗺️ ระบบจัดเส้นทาง Milk Run Logistics")

uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
    st.subheader("📝 1. ข้อมูลสถานที่")
    edited_df = st.data_editor(df, use_container_width=True)

    with st.expander("⚙️ 2. ตั้งค่าพารามิเตอร์ (ฝังค่าคอนฟิก)", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        empty_speed = col1.number_input("ความเร็วรถเปล่า (กม./ชม.)", value=50.0)
        full_speed = col2.number_input("ความเร็วรถตอนหนักสุด (กม./ชม.)", value=35.0)
        max_capacity = col3.number_input("ความจุรถสูงสุด (กก.)", value=1200.0)
        start_time = col4.time_input("เวลาออก", datetime.time(11, 0))
        
        c1, c2, c3, c4 = st.columns(4)
        service_time = c1.number_input("เวลาลงของ/จุด (นาที)", value=3)
        fuel_rate = c2.number_input("สิ้นเปลือง (กม./ลิตร)", value=10.0)
        co2_rate = c3.number_input("CO2 (kg/ลิตร)", value=2.70757206, format="%.8f")
        fuel_price = c4.number_input("ราคาน้ำมัน (บาท/ลิตร)", value=32.50)

    st.subheader("🧠 3. การจัดเส้นทาง")
    algo_choice = st.radio("รูปแบบ:", ["1. ลำดับตามไฟล์ดั้งเดิม", "2. Nearest Neighbor", "3. Sweep", "4. Insertion", "5. Saving"])
    
    # KML Logic for Option 1
    kml_geom = None
    if "1. ลำดับ" in algo_choice:
        kml_file = st.file_uploader("อัปโหลด KML (ถ้ามีเพื่อแสดงเส้นทางเดิม):", type=["kml"])
        if kml_file: kml_geom = extract_coords_from_kml(kml_file)
        optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)
    else:
        indices = {"2. Nearest": nearest_neighbor_route, "3. Sweep": sweep_route, "4. Insertion": nearest_insertion_route, "5. Saving": savings_route}
        algo = indices[algo_choice]
        optimized_df = edited_df.iloc[algo(edited_df) + [0]].reset_index(drop=True)

    # Simulation Logic
    weight_list = (pd.to_numeric(optimized_df['200cc'].fillna(0)) * 0.215 + 
                   pd.to_numeric(optimized_df['2L'].fillna(0)) * 2.070 + 
                   pd.to_numeric(optimized_df['5L'].fillna(0)) * 5.140 + 
                   pd.to_numeric(optimized_df['Yogurt'].fillna(0)) * 0.071).tolist()
    weight_list[-1] = 0
    total_w = sum(weight_list)
    curr_w = total_w
    
    # Render Map & Schedule
    m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
    # ใช้ kml_geom ถ้ามี หรือดึง OSRM
    if kml_geom:
        AntPath(kml_geom, color="blue", weight=5, delay=800).add_to(m)
    else:
        # ดึง OSRM ตามปกติ
        pass 
    
    # (เพิ่มตารางสรุป และส่วนการคำนวณตามโค้ดเดิมของคุณที่นี่)
    st.success(f"น้ำหนักรวมบรรทุก: {total_w:.2f} กก.")
    st.progress(min(total_w/max_capacity, 1.0))
    st.dataframe(optimized_df)
    st_folium(m, width=1000, height=500)
