# -*- coding: utf-8 -*-
"""
Ağ otomasyon yardımcı fonksiyonları.
Telnet komut şablonları ve switch ile etkileşim fonksiyonları burada bulunur.
Yorumlar Türkçe olarak yazılmıştır.
"""
from netmiko import ConnectHandler
import subprocess
import pandas as pd
import os
import re
import logging
from datetime import datetime

# Proje ana dizinini belirle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SWITCH_XLSX = os.path.join(BASE_DIR, 'switchler.xlsx')
USERS_XLSX = os.path.join(BASE_DIR, 'kullanicilar.xlsx')
LOG_FILE = os.path.join(BASE_DIR, 'islem_loglari.txt')

# Basit dosya tabanlı logger
logger = logging.getLogger('net_auto')
logger.setLevel(logging.INFO)
fh = logging.FileHandler(LOG_FILE)
formatter = logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
fh.setFormatter(formatter)
logger.addHandler(fh)


# Cisco IOS Telnet komut şablonları
# Türkçe yorum: Bu sözlükte sık kullanılan show ve konfigürasyon şablonları tutulur.
COMMAND_TEMPLATES = {
    'show_ip_arp': 'show ip arp {ip}',
    'show_mac': 'show mac address-table address {mac}',
    'show_run_int': 'show running-config interface {intf}',
    'show_int_desc': 'show interfaces description',
    # Hız sınırlama için kullanılacak policy isimlendirme şablonları
    'conf_t': 'configure terminal',
    'intf': 'interface {intf}',
    'no_service_policy': 'no service-policy output',
    'service_policy': 'service-policy output {policy}',
    'policy_map': 'policy-map {policy}',
    'class_default': 'class class-default',
    'police_bps': 'police {bps} conform-action transmit exceed-action drop',
    'end': 'end',
}


def ensure_excels_exist():
    """Excel dosyaları yoksa örnek içeriklerle oluşturur."""
    if not os.path.exists(SWITCH_XLSX):
        df = pd.DataFrame(columns=['Switch_Adi', 'IP_Adresi', 'Sifre'])
        df.to_excel(SWITCH_XLSX, index=False)
    if not os.path.exists(USERS_XLSX):
        df = pd.DataFrame(columns=['Kullanici_Adi', 'IP_Adresi'])
        df.to_excel(USERS_XLSX, index=False)


def load_data_from_excels():
    """Excel dosyalarını okuyup pandas DataFrame olarak döndürür."""
    ensure_excels_exist()
    switches = pd.read_excel(SWITCH_XLSX, engine='openpyxl')
    users = pd.read_excel(USERS_XLSX, engine='openpyxl')
    return users, switches


def check_switch_status(switch_ip, timeout=1000):
    """Switch'e ping atarak hızlı online/offline kontrolü yapar.
    Windows ortamı için `ping -n 1 -w timeout` komutu kullanılır.
    True dönerse online, False dönerse offline olarak değerlendirilir.
    """
    try:
        # Windows ping: -n 1 (bir paket), -w timeout(ms)
        res = subprocess.run(['ping', '-n', '1', '-w', str(timeout), switch_ip],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return res.returncode == 0
    except Exception:
        return False


def _connect_telnet(switch_ip, password, timeout=10):
    """Netmiko ile telnet bağlantısı açar. Kullanıcı adı boş gönderilir."""
    device = {
        'device_type': 'cisco_ios_telnet',
        'host': switch_ip,
        'username': '',
        'password': password,
        'secret': '',
    }
    conn = ConnectHandler(**device)
    return conn


def get_mac_from_ip(user_ip):
    """Kullanıcının IP'sine karşılık gelen MAC adresini switchlerde arar.
    Bulduğu ilk güncel/aktif eşleşmeyi döndürür: (mac_address, switch_ip)
    """
    users, switches = load_data_from_excels()
    for idx, sw in switches.iterrows():
        sw_ip = str(sw['IP_Adresi']).strip()
        pwd = str(sw['Sifre']) if 'Sifre' in sw and not pd.isna(sw['Sifre']) else ''
        if not check_switch_status(sw_ip):
            continue
        try:
            conn = _connect_telnet(sw_ip, pwd)
            cmd = COMMAND_TEMPLATES['show_ip_arp'].format(ip=user_ip)
            out = conn.send_command(cmd)
            conn.disconnect()
            # Basit parse: satır içinde MAC adresi patterni ara
            m = re.search(r'([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})', out)
            if m:
                mac = m.group(1)
                return mac, sw_ip
        except Exception:
            continue
    return None, None


def get_port_and_current_speed(mac_address):
    """MAC adresini tüm switchlerde arar, bağlı olduğu portu ve porttaki mevcut hız konfigürasyonunu döner.
    Döner: (switch_ip, port, speed_mbps_or_None)
    Eğer birden fazla sonuç varsa en güncel/aktif olanı seçmeye çalışır.
    """
    _, switches = load_data_from_excels()
    for idx, sw in switches.iterrows():
        sw_ip = str(sw['IP_Adresi']).strip()
        pwd = str(sw['Sifre']) if 'Sifre' in sw and not pd.isna(sw['Sifre']) else ''
        if not check_switch_status(sw_ip):
            continue
        try:
            conn = _connect_telnet(sw_ip, pwd)
            cmd = COMMAND_TEMPLATES['show_mac'].format(mac=mac_address)
            out = conn.send_command(cmd)
            # Çıktıda port bilgisini parse et
            # Örnek satır: "Vlan    Mac Address       Type        Ports"
            lines = out.splitlines()
            port = None
            for line in lines:
                if mac_address.lower().replace('.', '').upper() in line.replace('.', '').upper():
                    # satırda sondaki sütun port olmalı
                    parts = line.split()
                    if len(parts) >= 4:
                        port = parts[-1]
                        break
                    # alternatif parse: son kelime port
            if not port:
                conn.disconnect()
                continue
            # Şimdi running-config interface komutu ile hız bilgisi al
            run_out = conn.send_command(COMMAND_TEMPLATES['show_run_int'].format(intf=port))
            conn.disconnect()
            # Hız limitini arar (örnek: police 10000000) veya service-policy
            m = re.search(r'police\s+(\d+)', run_out)
            if m:
                bps = int(m.group(1))
                mbps = int(bps / 1_000_000)
                return sw_ip, port, mbps
            m2 = re.search(r'service-policy output (\S+)', run_out)
            if m2:
                policy = m2.group(1)
                # policy içinden hız çıkarmak için daha fazla sorgu gerekebilir; None döndürelim
                return sw_ip, port, None
            # Eğer yoksa None
            return sw_ip, port, None
        except Exception:
            continue
    return None, None, None


def apply_rate_limit(switch_ip, port, speed_mbps):
    """Verilen switch ve porta hız limiti uygular.
    Uplink koruması: ilgili port açıklamasında 'uplink' veya 'trunk' gibi kelimeler varsa reddeder.
    speed_mbps: int (ör. 10, 50) veya None (sınırsız - konfigürasyon kaldırılır)
    """
    # Log giriş fonksiyonu
    def _log(user, msg):
        logger.info(f"{user} - {msg}")

    # Önce switch info oku
    users, switches = load_data_from_excels()
    sw_row = switches[switches['IP_Adresi'].astype(str) == str(switch_ip)]
    pwd = ''
    if not sw_row.empty:
        pwd = str(sw_row.iloc[0]['Sifre']) if not pd.isna(sw_row.iloc[0]['Sifre']) else ''

    if not check_switch_status(switch_ip):
        _log('SYSTEM', f'Bağlantı hatası: {switch_ip} reachable değil')
        return False, 'Switch unreachable'

    try:
        conn = _connect_telnet(switch_ip, pwd)
        # Uplink koruması: port açıklamalarını kontrol et
        desc_out = conn.send_command(COMMAND_TEMPLATES['show_int_desc'])
        # Eğer satırlarda port ve açıklama varsa "Gi1/0/1 up    UPLINK to core" gibi
        for line in desc_out.splitlines():
            if port in line:
                if re.search(r'(?i)uplink|trunk|core|backbone', line):
                    conn.disconnect()
                    _log('SYSTEM', f'Uplink koruması: {switch_ip} {port} için değişiklik reddedildi')
                    return False, 'Uplink portu korumalı'

        cmds = []
        if speed_mbps is None:
            # Sınırsız: varsa service-policy kaldır
            cmds = [COMMAND_TEMPLATES['conf_t'], COMMAND_TEMPLATES['intf'].format(intf=port), COMMAND_TEMPLATES['no_service_policy'], COMMAND_TEMPLATES['end']]
        else:
            bps = int(speed_mbps * 1_000_000)
            policy = f'RATE_{port.replace("/","_")}'
            # Basit policy oluştur ve interface'e uygulama
            cmds = [
                COMMAND_TEMPLATES['conf_t'],
                COMMAND_TEMPLATES['policy_map'].format(policy=policy),
                COMMAND_TEMPLATES['class_default'],
                COMMAND_TEMPLATES['police_bps'].format(bps=bps),
                COMMAND_TEMPLATES['intf'].format(intf=port),
                COMMAND_TEMPLATES['service_policy'].format(policy=policy),
                COMMAND_TEMPLATES['end']
            ]

        # Komutları gönder
        output = ''
        for c in cmds:
            try:
                out = conn.send_config_set([c]) if c == COMMAND_TEMPLATES['conf_t'] or c.startswith('interface') or c.startswith('policy-map') else conn.send_command(c)
            except Exception:
                out = ''
            output += f"\n{c}\n{out}\n"

        conn.disconnect()
        # Loglama
        _log('APPLY', f'Port {port} - hız set: {speed_mbps} Mbps - switch {switch_ip} - çıktı: {output[:1000]}')
        return True, 'Applied'
    except Exception as e:
        _log('ERROR', f'Exception applying rate on {switch_ip} {port}: {e}')
        return False, str(e)


def add_switch_manual(switch_name, ip_address, password):
    """Yeni switch ekleme; hem belleğe hem de Excel dosyasına yazar."""
    ensure_excels_exist()
    switches = pd.read_excel(SWITCH_XLSX, engine='openpyxl')
    # Aynı IP daha önce eklenmişse üzerine yazma
    if (switches['IP_Adresi'].astype(str) == str(ip_address)).any():
        # Var olan satırı güncelle
        switches.loc[switches['IP_Adresi'].astype(str) == str(ip_address), ['Switch_Adi', 'Sifre']] = [switch_name, password]
    else:
        new_row = {'Switch_Adi': switch_name, 'IP_Adresi': ip_address, 'Sifre': password}
        switches = pd.concat([switches, pd.DataFrame([new_row])], ignore_index=True)
    switches.to_excel(SWITCH_XLSX, index=False)
    return True


def test_telnet_connection(switch_ip, password, timeout=10):
    """Verilen switch IP ve şifre ile kısa bir Telnet bağlantısı dener.
    Başarılıysa (True, mesaj), başarısızsa (False, hata mesajı) döner.
    Bu fonksiyon sadece bağlantı testi yapar, konfigürasyon değiştirmez.
    """
    try:
        conn = _connect_telnet(switch_ip, password, timeout=timeout)
        # Basit bir show komutu deneyelim
        out = conn.send_command('show version', expect_string=None)
        conn.disconnect()
        return True, 'Telnet bağlantısı başarılı'
    except Exception as e:
        return False, str(e)
