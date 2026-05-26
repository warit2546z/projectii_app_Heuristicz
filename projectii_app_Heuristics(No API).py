import streamlit as st
import pandas as pd
import folium
from folium.plugins import AntPath
from streamlit_folium import st_folium
import math
import datetime
import requests
import re

# --- ฟังก์ชันสร้างไฟล์ KML ---
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

# --- ฟังก์ชันสร้างไฟล์ GPX ---
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

# --- ฟังก์ชันหลัก ---
def get_osrm_route(df):
    try:
        coords = ";".join([f"{row['Lon']},{row['Lat']}" for _, row in df.iterrows()])
        url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
        response = requests.get(url, timeout=5).json()
        if response.get("code") == "Ok":
            route = response["routes"][0]
            geometry = [[coord[1], coord[0]] for coord in route["geometry"]["coordinates"]]
            return geometry
    except: pass
    # Fallback to straight line if API fails
    return [[row['Lat'], row['Lon']] for _, row in df.iterrows()]

# --- UI Setup ---
st.set_page_config(page_title="Milk Run Optimization", layout="wide")
st.title("🗺️ ระบบจัดเส้นทาง Milk Run Logistics")

uploaded_file = st.file_uploader("📂 อัปโหลดไฟล์ (Excel / CSV)", type=["xlsx", "csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith('.csv') else pd.read_excel(uploaded_file)
    st.subheader("📝 1. ข้อมูลสถานที่")
    edited_df = st.data_editor(df, use_container_width=True)

    # Simulation Logic (รวมการคำนวณน้ำหนักและเวลา)
    # ... (ส่วนคำนวณอัลกอริทึมเดิมของคุณที่นี่) ...
    
    # สมมติ optimized_df คือ dataframe ที่ผ่านการจัดเส้นทางแล้ว
    optimized_df = pd.concat([edited_df, edited_df.iloc[[0]]], ignore_index=True)
    
    # ดึงเส้นทาง
    geometry = get_osrm_route(optimized_df)
    
    st.subheader("📍 5. แผนที่เส้นทาง (Ant Path)")
    m = folium.Map(location=[optimized_df['Lat'].mean(), optimized_df['Lon'].mean()], zoom_start=14)
    
    # เพิ่ม Ant Path
    AntPath(geometry, color="blue", weight=5, delay=800).add_to(m)
    
    # เพิ่ม Marker
    for i, row in optimized_df.iterrows():
        folium.Marker([row['Lat'], row['Lon']], popup=row['ชื่อสถานที่']).add_to(m)
        
    st_folium(m, width=1000, height=500)

    # --- ฟังก์ชัน Export ---
    st.markdown("---")
    st.subheader("📥 6. ดาวน์โหลดข้อมูลเส้นทาง")
    col1, col2 = st.columns(2)
    
    kml_str = create_kml(optimized_df, [[lat, lon] for lat, lon in geometry])
    gpx_str = create_gpx(optimized_df, [[lat, lon] for lat, lon in geometry])
    
    col1.download_button("🌍 ดาวน์โหลด KML", kml_str, "route.kml", "application/vnd.google-earth.kml+xml")
    col2.download_button("📡 ดาวน์โหลด GPX", gpx_str, "route.gpx", "application/gpx+xml")
