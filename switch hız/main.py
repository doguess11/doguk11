# -*- coding: utf-8 -*-
"""
FastAPI backend for network management panel.
Türkçe yorumlar ile istenen fonksiyonlar ve API endpoint'leri burada bulunur.
"""
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import pandas as pd
import os
from utils import (
    load_data_from_excels,
    check_switch_status,
    get_mac_from_ip,
    get_port_and_current_speed,
    apply_rate_limit,
    add_switch_manual,
    test_telnet_connection,
    SWITCH_XLSX,
    USERS_XLSX,
    ensure_excels_exist,
)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ensure_excels_exist()

app.mount('/static', StaticFiles(directory=os.path.join(BASE_DIR, 'static')), name='static')


class ApplyRequest(BaseModel):
    kullanici_adi: str
    kullanici_ip: str
    speed_choice: str  # '10','50','unlimited'


@app.get('/')
def index():
    return FileResponse(os.path.join(BASE_DIR, 'static', 'index.html'))


@app.get('/api/users')
def api_users():
    users, switches = load_data_from_excels()
    # Her kullanıcı için MAC, port ve mevcut hız sorgula
    data = []
    for idx, u in users.iterrows():
        name = u['Kullanici_Adi']
        ip = str(u['IP_Adresi'])
        mac, sw_ip = get_mac_from_ip(ip)
        port = None
        cur_speed = None
        if mac:
            sw_ip2, port, cur_speed = get_port_and_current_speed(mac)
        data.append({'Kullanici_Adi': name, 'IP_Adresi': ip, 'Switch_IP': sw_ip or sw_ip2, 'Port': port, 'Mevcut_Hiz': cur_speed})
    return data


@app.get('/api/switches')
def api_switches():
    users, switches = load_data_from_excels()
    data = []
    for idx, sw in switches.iterrows():
        ip = str(sw['IP_Adresi'])
        name = sw['Switch_Adi']
        status = check_switch_status(ip)
        data.append({'Switch_Adi': name, 'IP_Adresi': ip, 'Online': status})
    return data


@app.post('/api/apply')
def api_apply(req: ApplyRequest):
    # Hız seçimini değerlendir
    if req.speed_choice == '10':
        speed = 10
    elif req.speed_choice == '50':
        speed = 50
    else:
        speed = None

    # IP'den MAC ve port bul
    mac, switch_ip = get_mac_from_ip(req.kullanici_ip)
    if not mac:
        raise HTTPException(status_code=404, detail='MAC bulunamadı')
    sw_ip, port, cur_speed = get_port_and_current_speed(mac)
    if not port or not sw_ip:
        raise HTTPException(status_code=404, detail='Port veya switch bulunamadı')

    ok, msg = apply_rate_limit(sw_ip, port, speed)
    if not ok:
        raise HTTPException(status_code=500, detail=msg)
    return {'status': 'ok', 'msg': msg}


@app.post('/api/add_switch')
def api_add_switch(name: str = Form(...), ip: str = Form(...), pwd: str = Form(...)):
    ok = add_switch_manual(name, ip, pwd)
    if not ok:
        raise HTTPException(status_code=500, detail='Excel yazma hatası')
    # Kısa telnet testi yap
    conn_ok, msg = test_telnet_connection(ip, pwd)
    return {'status': 'ok', 'telnet_ok': conn_ok, 'telnet_msg': msg}


if __name__ == '__main__':
    uvicorn.run('main:app', host='0.0.0.0', port=8000, reload=True)
