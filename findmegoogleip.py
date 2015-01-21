#! /usr/bin/python3

import random
import urllib.request
import json
import subprocess
import threading
import sys
import pprint
import time
import os
import socket
import ssl


class FindMeIP:
    def __init__(self, locations):
        self.locations = locations
        self.dns_servers = []
        self.resolved_ips = set()
        self.ip_with_time = []
        self.available_ips = []
        self.reachable = []

    @staticmethod
    def read_domains():
        with open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'domains.txt')) as file:
            return [line.strip() for line in file.readlines() if line.strip()]

    @staticmethod
    def run_threads(threads, limit=200):
        """A general way to run multiple threads"""
        lock = threading.Lock()
        for thread in threads:
            thread.lock = lock
            if threading.active_count() > limit:
                time.sleep(1)
                continue
            else:
                thread.start()

        for thread in threads:
            thread.join()

    def get_dns_servers(self):
        """Get the public dns server list from public-dns.tk"""
        if self.locations == 'all':
            self.locations = FindMeIP.read_domains()
        urls = ['http://public-dns.tk/nameserver/%s.json' % location for location in self.locations]

        threads = []
        for url in urls:
            threads.append(GetDnsServer(url, self.dns_servers))

        FindMeIP.run_threads(threads, 20)

    def lookup_ips(self):
        threads = []
        for server in self.dns_servers:
            threads.append(NsLookup('google.com', server, self.resolved_ips))

        FindMeIP.run_threads(threads)

    def ping(self):
        ping_results = {}
        threads = []
        for ip in self.resolved_ips:
            threads.append(Ping(ip, ping_results))

        FindMeIP.run_threads(threads)

        for k, v in ping_results.items():
            if v['loss'] == 0:
                self.ip_with_time.append((k, v['time']))

        self.ip_with_time = sorted(self.ip_with_time, key=lambda x: x[1])
        self.available_ips = [x[0] for x in self.ip_with_time]

    def check_service(self):
        threads = []
        for ip in self.available_ips:
            threads.append(ServiceCheck(ip, self.reachable))

        FindMeIP.run_threads(threads)

    def show_results(self):
        if self.reachable:
            reachable_ip_with_time = [(ip, rtt) for (ip, rtt) in self.ip_with_time if ip in self.reachable]
            print("%d IPs ordered by delay time:" % len(reachable_ip_with_time))
            pprint.PrettyPrinter().pprint(reachable_ip_with_time)
            print("%d IPs concatenated:" % len(self.reachable))
            print('|'.join(self.reachable))
        else:
            print("No available servers found")

    def run(self):
        self.get_dns_servers()
        self.lookup_ips()
        self.ping()
        self.check_service()
        self.show_results()


class ServiceCheck(threading.Thread):
    def __init__(self, ip, servicing):
        threading.Thread.__init__(self)
        self.ip = ip
        self.port = 443
        self.lock = None
        self.servicing = servicing

    def run(self):
        try:
            print('checking ssl service %s:%s' % (self.ip, self.port))
            socket.setdefaulttimeout(2)
            conn = ssl.create_default_context().wrap_socket(socket.socket(), server_hostname="www.google.com")
            conn.connect((self.ip, self.port))
            self.lock.acquire()
            self.servicing.append(self.ip)
            self.lock.release()
        except (ssl.CertificateError, socket.timeout) as err:
            print("error(%s) on connecting %s:%s" % (str(err), self.ip, self.port))


class GetDnsServer(threading.Thread):
    def __init__(self, url, dns_servers):
        threading.Thread.__init__(self)
        self.url = url
        self.lock = None
        self.dns_servers = dns_servers

    def run(self):
        try:
            print('retrieving dns servers from %s' % self.url)
            data = urllib.request.urlopen(self.url).read().decode()
            servers = json.loads(data)
            self.lock.acquire()
            for server in servers:
                if '.' in server['ip']:
                    self.dns_servers.append(server['ip'])
            self.lock.release()
        except IOError:
            print("Cannot get data from %s" % self.url)


class NsLookup(threading.Thread):
    def __init__(self, name, server, store):
        threading.Thread.__init__(self)
        self.name = name
        self.server = server
        self.lock = None
        self.store = store

    def run(self):
        try:
            print('looking up %s from %s' % (self.name, self.server))
            output = subprocess.check_output(["nslookup", self.name, self.server])
            ips = self.parse_nslookup_result(output.decode())
            self.lock.acquire()
            for ip in ips:
                # google is heavily blocked in china, most of these official addresses won't work
                if 'google' in self.name and (ip.startswith('74.') or ip.startswith('173.')):
                    continue
                self.store.add(ip)
            self.lock.release()
        except subprocess.CalledProcessError:
            pass

    @staticmethod
    def parse_nslookup_result(result):
        """Parse the result of nslookup and return a list of ip"""
        ips = []
        lines = result.split('\n')
        del lines[0]
        del lines[1]
        for line in lines:
            if line.startswith('Address: '):
                ips.append(line.replace('Address: ', ''))
        return ips


class Ping(threading.Thread):
    def __init__(self, server, store):
        threading.Thread.__init__(self)
        self.server = server
        self.lock = None
        self.store = store

    def run(self):
        try:
            print('pinging %s' % (self.server,))
            output = subprocess.check_output(["ping", '-c 5', '-q', self.server])
            self.lock.acquire()
            self.store[self.server] = self.parse_ping_result(output.decode())
            self.lock.release()
        except subprocess.CalledProcessError:
            pass

    @staticmethod
    def parse_ping_result(result):
        loss = result.split('\n')[-3].split(', ')[2].split(' ')[0].replace('%', '')
        trip_time = result.split('\n')[-2].split(' = ')[-1].split('/')[1]
        return {'loss': float(loss), 'time': float(trip_time)}


if len(sys.argv) >= 2:
        FindMeIP(sys.argv[1:]).run()
else:
    print("Usage:")
    print("Find ips in specified domains: findmegoogleip.py kr us")
    print("=" * 50)
    print("Now running default: find ip from a random chosen domain")
    FindMeIP([random.choice(FindMeIP.read_domains())]).run()
