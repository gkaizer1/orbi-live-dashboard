#!/usr/bin/env python

from flask import Flask, render_template
import requests
from requests.auth import HTTPBasicAuth
from html.parser import HTMLParser
import time
import datetime
import re
import json
import argparse

from pynetgear import Netgear
import threading
import os
import sys, traceback

netgear = Netgear(password=os.environ['ROUTER_ADMIN_PASSWORD'])

app = Flask(__name__, static_url_path='', static_folder='./')

__router_status = {}
__last_updated = None
__started_time = datetime.datetime.now()
__traffic_last_updated = datetime.datetime.now()
__traffic = {}
__devices = []
__stop = False


def datetime_handler(x):
    if isinstance(x, datetime.datetime):
        return x.isoformat()
    return str(x)


@app.route('/', methods=['GET'])
def serve_html():
    print('serving html')
    return app.send_static_file('index.html')


@app.route("/devices", methods=['GET'])
def devices():
    return json.dumps(__devices, indent=4, default=datetime_handler)


@app.route("/traffic", methods=['GET'])
def traffic():
    return json.dumps(__traffic, indent=4, default=datetime_handler)


@app.route("/router_stats", methods=['GET'])
def router_stats():
    return json.dumps({
        'stats': __router_status,
        'traffic': __traffic,
        'devices': __devices,
        'lastUpdated': __last_updated
    }, indent=4, default=datetime_handler)


@app.route("/status", methods=['GET'])
def stats():
    return json.dumps({
        'uptimeSeconds': (datetime.datetime.now() - __started_time).seconds,
        'lastUpdated': (datetime.datetime.now() - __last_updated).seconds,
    }, indent=4)


class ScriptOnlyHTMLParser(HTMLParser):
    def __init__(self):
        super(ScriptOnlyHTMLParser, self).__init__()
        self._script = ""
        self._is_script_tag = False

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            self._is_script_tag = False
            return
        self._is_script_tag = True

    def handle_endtag(self, tag):
        if tag != "script":
            return
        self._is_script_tag = False

    def handle_data(self, data):
        if not self._is_script_tag:
            return

        if not data.strip():
            return
        self._script += data.strip()

    @property
    def script(self):
        return self._script

    def parse_var_declarations(self):
        p = re.compile("var.*\\;")
        var_declarations = p.findall(self._script)
        results = {}
        for declaration in var_declarations:
            var_name = declaration.split('=')[0].replace(
                'var ', '').replace('let ', '')

            var_value = ''
            if '=' in declaration:
                var_value = declaration.split(
                    '=')[1].replace('"', '').replace(';', '')
            results[var_name] = var_value
        return results


def update_devices_stats():
    while not __stop:
        global __devices
        try:
            # Get devices
            total_devices = []
            devices = netgear.get_attached_devices()
            for device in devices:
                total_devices.append({
                    'name': device[0],
                    'ip': device[1]
                })
            __devices = total_devices
        except:
            traceback.print_exc()
        finally:
            time.sleep(30)


def update_traffic_stats(update_interval):
    global __traffic
    global __traffic_last_updated

    while not __stop:
        # Get traffic data
        response = requests.get(
            'http://192.168.1.1/traffic.htm', auth=HTTPBasicAuth('admin', os.environ['ROUTER_ADMIN_PASSWORD']))
        if response.status_code < 200 or response.status_code > 299:
            __router_status = {}
            return

        # Update download rate
        down_prev = 0
        up_prev = 0

        if __traffic:
            down_prev = __traffic['traffic_today_down'].replace(',', '')

        # Update upload-rate
        if __traffic:
            up_prev = __traffic['traffic_today_up'].replace(',', '')

        parser = ScriptOnlyHTMLParser()
        parser.feed(response.text)
        __traffic = parser.parse_var_declarations()

        try:
            seconds_elapsed = (datetime.datetime.now() - __traffic_last_updated).total_seconds()
            __traffic['down_speed_mb'] = (float(__traffic['traffic_today_down'].replace(',', '')) - float(down_prev)) / seconds_elapsed
            __traffic['down_speed_mb'] = int(__traffic['down_speed_mb'])
        except:
            traceback.print_exc()
            __traffic['down_speed_mb'] = 'unknown'

        try:
            seconds_elapsed = (datetime.datetime.now() - __traffic_last_updated).total_seconds()
            __traffic['up_speed_mb'] = (float(__traffic['traffic_today_up'].replace(
                ',', '')) - float(up_prev)) / seconds_elapsed
            __traffic['up_speed_mb'] = int(__traffic['up_speed_mb'])
        except:
            traceback.print_exc()
            __traffic['up_speed_mb'] = 'unknown'

        __traffic_last_updated = datetime.datetime.now()
        print('traffic stats updated')
        time.sleep(update_interval)


def update_status(update_interval):
    global __router_status
    global __last_updated

    while not __stop:
        try:
            # Get General stats
            response = requests.get(
                'http://192.168.1.1/RST_statistic.htm', auth=HTTPBasicAuth('admin', os.environ['ROUTER_ADMIN_PASSWORD']))
            if response.status_code < 200 or response.status_code > 299:
                __router_status = {}
                return

            parser = ScriptOnlyHTMLParser()
            parser.feed(response.text)
            __router_status = parser.parse_var_declarations()

            __last_updated = datetime.datetime.now()
        except:
            traceback.print_exc()
            pass

        print('stats updated')
        time.sleep(update_interval)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='orbit router status service')
    parser.add_argument('--port', '-p', type=int,
                        help='Port to run this service on', default=8091)
    parser.add_argument('--update-interval', '-f', type=int,
                        help='Interval between updates of traffic & stats in seconds', default=5)
    args = parser.parse_args()

    update_status_thread = threading.Thread(target=update_status, args=(args.update_interval,))
    update_status_thread.start()

    update_traffic_thread = threading.Thread(target=update_traffic_stats, args=(args.update_interval,))
    update_traffic_thread.start()

    update_device_thread = threading.Thread(target=update_devices_stats)
    update_device_thread.start()

    app.run(port=args.port, host='0.0.0.0')

    print('Setting stop flag')
    __stop = True
    update_device_thread.join()
    update_status_thread.join()
    update_traffic_thread.join()
