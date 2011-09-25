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
import logging as log
import sys


"""Setup logging"""
log.basicConfig(filename = '/var/log/gun.log',
                format='[%(asctime)s]: %(levelname)s: %(message)s',
                datefmt = '%Y-%m-%d, %H:%M:%S',
                level = log.DEBUG)

"""Reading all the configuration"""
config = ConfigParser.RawConfigParser()
if config.read('/etc/gun.conf') != []:
    pass
else:
    log.critical('Cannot open configuration file')
    sys.exit('Cannot open configuration file')

try:
    SYNC_OVERLAYS = config.getboolean('GENERAL', 'sync_overlays')
    SYNC_TREE_COMMAND = config.get('SYNC', 'tree_command')
    SYNC_TREE_OPTIONS = config.get('SYNC', 'tree_options')
    if SYNC_OVERLAYS:
        SYNC_OVERLAYS_COMMAND = config.get('SYNC', 'overlays_command')
        SYNC_OVERLAYS_OPTIONS = config.get('SYNC', 'overlays_options')
    EMERGE_COMMAND = config.get('UPDATE', 'command')
    EMERGE_OPTIONS = config.get('UPDATE', 'options')
    EMAIL_NOTIFY = config.getboolean('NOTIFY', 'email')
    JABBER_NOTIFY = config.getboolean('NOTIFY', 'jabber')

    MAIL_HOST = config.get('EMAIL', 'host')
    MAIL_USER = config.get('EMAIL', 'user')
    MAIL_PASSWORD = config.get('EMAIL', 'password')
    MAIL_PORT = config.get('EMAIL', 'port')
    MAIL_SENDER = config.get('EMAIL', 'mailfrom')
    MAIL_RECIPIENT = config.get('EMAIL', 'mailto')
    JABBER_SENDER = config.get('JABBER', 'jabber_from')
    JABBER_PASSWORD = config.get('JABBER', 'password')
    JABBER_RECIPIENT = config.get('JABBER', 'jabber_to')
except ConfigParser.NoSectionError, error:
    log.critical('Errors reading config file: %s' % (error))
    sys.exit('Errors reading config file: %s' % (error))
except ConfigParser.NoOptionError, error:
    log.critical('Errors reading config file: %s' % (error))
    sys.exit('Errors reading config file: %s' % (error))

timestamp = time.strftime('%Y%m%d-%H%M%S')
"""Creating tempfile"""
try:
    OUTPUT_FILE = tempfile.NamedTemporaryFile(suffix = '',
                                              prefix = 'gun-',
                                              dir = '/var/tmp',
                                              delete = True)
except OSError, error:
    log.critical('Cannot create tempfile: %s' % (error))
    sys.exit('Cannot create tempfile: %s' % (error))
    

"""A replacement dict, that maps ANSI escape codes to HTML tags to use
within the formatter function"""
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
        log.info('gun started')
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
        output = subprocess.Popen(args = command,
                                  shell = True,
                                  stdout = stdout)
        output.communicate()
        
        return output
    
    def sync(self):
        """Sync Portage tree and overlays
        """
        command = '%s %s' % (SYNC_TREE_COMMAND, SYNC_TREE_OPTIONS)
        log.info('Running sync tree command: "%s"' % (command))
        self._execute_command(command = command,
                              stdout = subprocess.PIPE)
        
        if SYNC_OVERLAYS:
            command = '%s %s' % (SYNC_OVERLAYS_COMMAND, SYNC_OVERLAYS_OPTIONS)
            log.info('Running sync overlays command: "%s"' % (command))
            self._execute_command(command = command,
                                  stdout = subprocess.PIPE)
        else:
            log.info('Sync overlays not requested. Skipping.')

    def pretend_update(self):
        """Runs the emerge command to get the list of packages ready for update.
        Writes the list to file.
        """
        command = '%s %s --pretend --color y' % (EMERGE_COMMAND, EMERGE_OPTIONS)
        log.info('Running emerge: "%s"' % (command))
        output = self._execute_command(command = command,
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
    def __init__(self, input_file):
        try:
            self.text = input_file.read()
        except OSError, error:
            log.error('Cannot open output file for formatting: %s' % (error))
        input_file.seek(0)
            
    def formatter(self, escape_map):
        """Parses the output file and replaces ANSI terminal escape codes
        """
        # Remove 'header' and 'footer' from the file
        stripped_text = re.sub(pattern = '(?s).*?(\[\x1b\[32mebuild)',
                               repl = '\\1',
                               string = self.text,
                               count = 1)
        pattern = '|'.join(map(re.escape,
                               escape_map.keys()))
        formatted_body = re.sub(pattern = pattern,
                                repl = lambda m:escape_map[m.group()],
                                string = stripped_text)
    
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
        message = self.formatter(escape_map = plaintext_map)
        
        return message
        
    def as_html(self):
        """...as HTML
        """
        message = self.formatter(escape_map = ESCAPE_MAP)
        
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
        except socket.error, error:
            log.error('Cannot connect to SMTP server: %s: %s:%s' % (error,
                                                                    host,
                                                                    port))
        else:
            try:
                self.smtp.login(user = user,
                                password = password)
            except smtplib.SMTPAuthenticationError:
                log.error('Cannot authenticate on SMTP server: %d, %s' % (error[0],
                                                                          error[1]))
            
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
        body = Message(input_file = OUTPUT_FILE)
        message = body.as_html()
        message = headers + html_header + message + html_footer
        try:
            log.info('Sending Email message')
            self.smtp.sendmail(from_addr = MAIL_SENDER,
                               to_addrs = MAIL_RECIPIENT,
                               msg = message)
        except smtplib.SMTPRecipientsRefused, error:
            log.error('Cannot send email: %s' % (error))
        except smtplib.SMTPServerDisconnected:
            pass
        
    def disconnect(self):
        """Disconnects from SMTP server
        """
        try:
            self.smtp.quit()
        except smtplib.SMTPServerDisconnected:
            pass
        

class JabberError(Exception):
    """Jabber exceptions class
    """
    def connect_error(self):
        raise IOError('Cannot connect to Jabber server')
    
    def auth_error(self):
        raise IOError('Cannot authenticate on Jabber server')
    

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
            try:
                JabberError().connect_error(), error
            except IOError, error:
                log.error('%s: %s' % (error, jabberid.getDomain()))
                
        else:
            if not self.client.auth(user = jabberid.getNode(),
                                    password = password,
                                    resource = jabberid.getResource()):
                try:
                    JabberError().auth_error(), error
                except IOError, error:
                    log.error(error)
            
    def send(self):
        """Sends Jabber message
        """
        body = Message(input_file = OUTPUT_FILE)
        message = body.as_plaintext()
        try:
            log.info('Sending Jabber message')
            self.client.send(xmpp.protocol.Message(to = JABBER_RECIPIENT,
                                                   body = message))
        except AttributeError:
            pass
        
    def disconnect(self):
        """Disconnects from XMPP server
        """
        try:
            self.client.disconnect()
        except AttributeError:
            pass
            
            
def main():
    g = Gun()
    g.sync()
    g.pretend_update()
    g.notify()