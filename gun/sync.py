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


COLORS = {'\x1b[32m': '</span><span style="color:darkgreen;font-weight:normal">',
          '\x1b[36;01m': '</span><span style="color:turquoise;font-weight:bold">',
          '\x1b[34;01m': '</span><span style="color:blue;font-weight:bold">',
          '\x1b[39;49;00m': '</span><span style="color:black;font-weight:normal">',
          '\x1b[33;01m': '</span><span style="color:orange;font-weight:bold">',
          '\x1b[32;01m': '</span><span style="color:limegreen;font-weight:bold">',
          '\x1b[31;01m': '</span><span style="color:red;font-weight:bold">',
          '\x0d': '<br>'
          }


class Timestamp(tempfile._RandomNameSequence):
    def next(self):
        return time.strftime('%Y%m%d-%H%M%S')

tempfile._RandomNameSequence = Timestamp

class GUN():
    """Main class
    """

    def __init__(self):
        """Reads configuration file, performs basic setup
        """
        config = ConfigParser.RawConfigParser()
        try:
            config.read('/etc/gun.conf')
        except IOError:
            print 'Cannot open configuration file'
        
        # General settings
        self.sync_overlays = config.getboolean('GENERAL', 'sync_overlays')
        
        # Synchronization settings
        self.sync_tree_command = config.get('SYNC', 'tree_command')
        if self.sync_overlays:
            self.sync_overlays_command = config.get('SYNC', 'overlays_command')
        emerge_command = config.get('UPDATE', 'command')
    
        # Notification settings
        self.email_notify = config.getboolean('NOTIFY', 'email')
        self.jabber_notify = config.getboolean('NOTIFY', 'jabber')
        
        # Email settings
        self.mail_host = config.get('EMAIL', 'host')
        self.mail_user = config.get('EMAIL', 'user')
        self.mail_password = config.get('EMAIL', 'password')
        self.mail_port = config.get('EMAIL', 'port')
        self.mail_sender = config.get('EMAIL', 'mailfrom')
        self.mail_recipient = config.get('EMAIL', 'mailto')
        
        # Jabber settings
        self.jabber_sender = config.get('JABBER', 'jabber_from')
        self.jabber_password = config.get('JABBER', 'password')
        self.jabber_recipient = config.get('JABBER', 'jabber_to')

        # Output file
        timestamp = time.strftime('%Y%m%d-%H%M%S')
        self.output_file = tempfile.NamedTemporaryFile(suffix = '',
                                                       prefix = 'gun-',
                                                       dir = '/var/tmp',
                                                       delete = False)
        
        self.update_command = 'script -q -c \'%s\' -f %s' % (emerge_command,
                                                             self.output_file.name)
    
    def sync(self):
        """SYNC Portage tree and overlays
        """
        output = subprocess.Popen([self.sync_tree_command],
                                  shell=True,
                                  stdout=subprocess.PIPE)
        output.communicate()
        if self.sync_overlays:
            output = subprocess.Popen([self.sync_overlays_command],
                                      shell=True,
                                      stdout=subprocess.PIPE)
            output.communicate()

    def pretend_update(self):
        """Runs emerge to get the list of packages ready for upgrade.
        Writes the list to file.
        """
        output = subprocess.Popen([self.update_command],
                                  shell=True)
        output.communicate()
        self.output_file.seek(0)
        
    def _ansi2html(self, colors):
        """Parses the output file, produced by the script Linux tool and
        translates ANSI terminal color codes into HTML tags
        """
        # Remove 'header' and 'footer' from the file
        text = re.sub("(?s).*?(\[\x1b\[32mebuild)",
                      "\\1",
                      self.output_file.read(),
                      1).split('Total', 1)[0]
        pattern = '|'.join(map(re.escape, colors.keys()))
        message = re.sub(pattern,
                         lambda m:colors[m.group()],
                         text)
        self.output_file.seek(0)
        
        return message

    def _send_email(self):
        headers = ("From: %s\r\nTo: %s\r\nSubject: [%s] %s Packages to update\r\nContent-Type: text/html; charset=utf-8\r\n"
                   % (self.mail_sender,
                      self.mail_recipient,
                      os.uname()[1],
                      time.strftime('%Y-%m-%d')))
        message = headers + self._ansi2html(colors = COLORS)
        server = smtplib.SMTP()
        try:
            server.connect(self.mail_host,
                            self.mail_port)
        except socket.error:
            print 'Cannot connect to SMTP server'
        try:
            server.login(self.mail_user,
                         self.mail_password)
        except smtplib.SMTPAuthenticationError:
            print 'Cannot authenticate on SMTP server'
        server.sendmail(self.mail_sender,
                        self.mail_recipient,
                        message)
        server.quit()
    
    def _send_jabber(self):
        for key in COLORS.iterkeys():
            COLORS[key] = ''
        message = self._ansi2html(colors = COLORS)
        jid = xmpp.protocol.JID(self.jabber_sender)
        cl = xmpp.Client(jid.getDomain(),
                         debug=[])
        if not cl.connect():
            raise IOError('Cannot connect to Jabber server')
        else:
            if not cl.auth(jid.getNode(),
                           self.jabber_password,
                           resource=jid.getResource()):
                raise IOError('Cannot authenticate on Jabber server')
            else:
                cl.send(xmpp.protocol.Message(self.jabber_recipient,
                                              message))
        cl.disconnect()

    def notify(self):
        if self.email_notify:
            self._send_email()
        if self.jabber_notify:
            self._send_jabber()
            
            
def main():
    s = GUN()
    s.sync()
    s.pretend_update()
    s.notify()

# EOF