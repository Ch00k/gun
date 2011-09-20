# !/usr/bin/env python
#  -*- coding: utf-8 -*-

"""
A Python script that checks for Portage tree and overlays updates and notifies
of the list of packages available for upgrade.
This tool was inspired by Porticron (https://github.com/hollow/porticron)
by Benedikt Böhm aka hollow.
"""

import os
import subprocess
import smtplib
import socket
import ConfigParser
import xmpp
import re
import tempfile
import time


"""Reading all the configuration"""
config = ConfigParser.RawConfigParser()
try:
    config.read('/etc/gun.conf')
except IOError:
    print 'Cannot open configuration file'
timestamp = time.strftime('%Y%m%d-%H%M%S')
sync_overlays = config.getboolean('GENERAL', 'sync_overlays')
SYNC_TREE_COMMAND = config.get('SYNC', 'tree_command')
SYNC_OVERLAYS_COMMAND = config.get('SYNC', 'overlays_command') if sync_overlays else None
EMERGE_COMMAND = config.get('UPDATE', 'command')
EMAIL_NOTIFY = config.getboolean('NOTIFY', 'email')
JABBER_NOTIFY = config.getboolean('NOTIFY', 'jabber')
OUTPUT_FILE = tempfile.NamedTemporaryFile(suffix = '',
                                          prefix = 'gun-',
                                          dir = '/var/tmp',
                                          delete = True)
MAIL_HOST = config.get('EMAIL', 'host')
MAIL_USER = config.get('EMAIL', 'user')
MAIL_PASSWORD = config.get('EMAIL', 'password')
MAIL_PORT = config.get('EMAIL', 'port')
MAIL_SENDER = config.get('EMAIL', 'mailfrom')
MAIL_RECIPIENT = config.get('EMAIL', 'mailto')
JABBER_SENDER = config.get('JABBER', 'jabber_from')
JABBER_PASSWORD = config.get('JABBER', 'password')
JABBER_RECIPIENT = config.get('JABBER', 'jabber_to')

"""A replacement dict, that maps ANSI escape codes to HTML style tags to use
within formatter function"""
ESCAPE_MAP = {'\x1b[32m': '</span><span style="color:darkgreen;font-weight:normal">',
              '\x1b[36;01m': '</span><span style="color:turquoise;font-weight:bold">',
              '\x1b[34;01m': '</span><span style="color:blue;font-weight:bold">',
              '\x1b[39;49;00m': '</span><span style="color:black;font-weight:normal">',
              '\x1b[33;01m': '</span><span style="color:orange;font-weight:bold">',
              '\x1b[32;01m': '</span><span style="color:limegreen;font-weight:bold">',
              '\x1b[31;01m': '</span><span style="color:red;font-weight:bold">',
              '\n': '<br>',
              }


class Gun(object):
    """Main class
    """

    def __init__(self):
        """Createss a list of notifiers according to the notification
        configuration
        """
        self.notifiers = []
        if EMAIL_NOTIFY:
            self.notifiers.append(EmailNotifier(host = MAIL_HOST,
                                                port = MAIL_PORT,
                                                user = MAIL_USER,
                                                password = MAIL_PASSWORD)
                                  )
        if JABBER_NOTIFY:
            self.notifiers.append(JabberNotifier(jid = JABBER_SENDER,
                                                 password = JABBER_PASSWORD)
                                  )
    
    def _execute_command(self, command, stdout=None):
        """A helper function for command execution
        """
        output = subprocess.Popen(args = [command],
                                  shell = True,
                                  stdout = stdout)
        output.communicate()
        
        return output
    
    def sync(self):
        """Sync Portage tree and overlays
        """
        self._execute_command(command = SYNC_TREE_COMMAND,
                              stdout = subprocess.PIPE)
        
        if SYNC_OVERLAYS_COMMAND is not None:
            self._execute_command(command = SYNC_OVERLAYS_COMMAND,
                                  stdout = subprocess.PIPE)

    def pretend_update(self):
        """Runs the emerge command to get the list of packages ready for update.
        Writes the list to file.
        """
        output = self._execute_command(command = EMERGE_COMMAND,
                                       stdout = OUTPUT_FILE)
        OUTPUT_FILE.seek(0)
        
    def notify(self):
        """Sends updates notifications
        """
        for notifier in self.notifiers:
            notifier.send()
            notifier.disconnect()


class Message(object):
    """Formats the message body...
    """
    def formatter(self, input_file, escape_map):
        """Parses the output file and replaces ANSI terminal escape codes
        """
        # Remove 'header' and 'footer' from the file
        stripped_text = re.sub(pattern = '(?s).*?(\[\x1b\[32mebuild)',
                               repl = '\\1',
                               string = input_file.read(),
                               count = 1)
        pattern = '|'.join(map(re.escape,
                               escape_map.keys()))
        formatted_body = re.sub(pattern = pattern,
                                repl = lambda m:escape_map[m.group()],
                                string = stripped_text)
        input_file.seek(0)
    
        return formatted_body
    
    def as_plaintext(self):
        """...as plain text
        """
        plaintext_map = ESCAPE_MAP
        # We will delete the '\n' element from the dictionary since we do not
        # want the newlines to be replaced in plain text
        map(plaintext_map.pop, ['\n'], [])
        # Replacing the values in dictionary with empty values
        for key in plaintext_map.iterkeys():
            plaintext_map[key] = ''
        message = self.formatter(input_file = OUTPUT_FILE,
                                 escape_map = plaintext_map)
        
        return message
        
    def as_html(self):
        """...as HTML
        """
        message = self.formatter(input_file = OUTPUT_FILE,
                                 escape_map = ESCAPE_MAP)
        
        return message
        

class EmailNotifier(object):
    """Emails notifier class
    """
    def __init__(self, host, port, user, password):
        """Creates a connection to SMTP server and performs SMTP authentication
        """
        self.smtp = smtplib.SMTP()
        try:
            self.smtp.connect(host = host,
                              port = port)
        except socket.error:
            print 'Cannot connect to SMTP server'
        try:
            self.smtp.login(user = user,
                            password = password)
        except smtplib.SMTPAuthenticationError:
            print 'Cannot authenticate on SMTP server'
            
    def send(self):
        """Compiles an email message and sends it
        """
        headers = ("From: %s\r\nTo: %s\r\nSubject: [%s] %s Packages to update\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
                   % (MAIL_SENDER,
                      MAIL_RECIPIENT,
                      os.uname()[1],
                      time.strftime('%Y-%m-%d')))
        html_header = '<html><head></head><body>\r\n<style type="text/css">\r\np\r\n{\r\nfont-family:monospace;\r\n}\r\n</style>\r\n<p>'
        html_footer = '</p></body></html>'
        body = Message()
        message = body.as_html()
        message = headers + html_header + message + html_footer
        self.smtp.sendmail(from_addr = MAIL_SENDER,
                           to_addrs = MAIL_RECIPIENT,
                           msg = message)
        
    def disconnect(self):
        """Disconnects from SMTP server
        """
        self.smtp.quit()
        

class JabberNotifier(object):
    """Jabber notifier class
    """
    def __init__(self, jid, password):
        """Creates a connection to XMPP server and performs user authentication
        """
        jabberid = xmpp.protocol.JID(jid = jid)
        self.client = xmpp.Client(server = jabberid.getDomain(),
                                  debug = [])
        if not self.client.connect():
            raise IOError('Cannot connect to Jabber server')
        else:
            if not self.client.auth(user = jabberid.getNode(),
                                    password = password,
                                    resource = jabberid.getResource()):
                raise IOError('Cannot authenticate on Jabber server')
            
    def send(self):
        """Sends Jabber message
        """
        body = Message()
        message = body.as_plaintext()
        self.client.send(xmpp.protocol.Message(to = JABBER_RECIPIENT,
                                               body = message))
        
    def disconnect(self):
        """Disconnects from XMPP server
        """
        self.client.disconnect()
            
            
def main():
    g = Gun()
    g.sync()
    g.pretend_update()
    g.notify()
    