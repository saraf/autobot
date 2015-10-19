#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A full featured python IRC bot"""

import configparser
import socket
import ssl
import time
import datetime
import re
import sys
import select
import irc.bot
import codecs
from threading import Thread, Timer
from plugins.passive import url_announce, LogFile


# Create our bot class
class AutoBot(irc.bot.SingleServerIRCBot):
    """Create the single server irc bot"""
    def __init__(self, nick, name, nickpass, prefix, log_scheme, channels, network, listenhost, listenport, port=6667, usessl=False):
        """Connect to the IRC server"""
        if usessl:
            factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
        else:
            factory = irc.connection.Factory()

        try:
            irc.bot.SingleServerIRCBot.__init__(self, [(network, port)], nick, name, connect_factory = factory)
        except irc.client.ServerConnectionError:
            sys.stderr.write(sys.exc_info()[1])

        self.nick = nick
        self.channel_list = channels
        self.nickpass = nickpass
        self.prefix = prefix
        self.log_scheme = log_scheme
        self.logs = {}
        self.logs['autobot'] = LogFile.LogFile(datetime.datetime.utcnow().strftime(log_scheme).format(channel='autobot'))
        for ch in channels:
            log_name = datetime.datetime.utcnow().strftime(log_scheme).format(channel=ch)
            self.logs[ch] = LogFile.LogFile(log_name)

        Timer(960, self.refresh_logs).start()

        self.connection.add_global_handler("quit", self.alt_on_quit, -30)

        self.inputthread = TCPinput(self.connection, self, listenhost, listenport)
        self.inputthread.start()

    def start(self):
        try:
            super().start()
        except:
            self.close_logs()
            raise

    def say(self, target, text):
        """Send message to IRC and log it"""
        self.connection.privmsg(target, text)
        self.log_message(target, self.nick, text)

    def on_nicknameinuse(self, connection, event):
        """If the nick is in use, get nick_"""
        connection.nick(connection.get_nickname() + "_")

    def on_welcome(self, connection, event):
        """Join channels and regain nick"""
        for channel in self.channel_list:
            connection.join(channel)
            self.log_message("autobot", "info", "Joined channel %s" % (channel))
        if self.nickpass and connection.get_nickname() != self.nick:
            connection.privmsg("nickserv", "ghost %s %s" % (self.nick, self.nickpass))
            self.log_message("autobot", "info", "Recovered nick")

    def get_version(self):
        """CTCP version reply"""
        return "Autobot IRC bot"

    def on_privnotice(self, connection, event):
        """Identify to nickserv and log privnotices"""
        self.log_message("autobot", event.source, event.arguments[0])
        if not event.source:
            return
        source = event.source.nick
        if source and source.lower() == "nickserv":
            if event.arguments[0].lower().find("identify") >= 0:
                if self.nickpass and self.nick == connection.get_nickname():
                    connection.privmsg("nickserv", "identify %s %s" % (self.nick, self.nickpass))
                    self.log_message("autobot", "info", "Identified to nickserv")

    #def on_disconnect(self, connection, event):

    def on_pubnotice(self, connection, event):
        self.log_message(event.target, "notice", event.source + ": " + event.arguments[0])

    def on_kick(self, connection, event):
        """Log kicked nicks and rejoin channels if bot is kicked"""
        kickedNick = event.arguments[0]
        kicker = event.source.nick
        self.log_message(event.target, "info", "%s was kicked from the channel by %s" % (kickedNick, kicker))
        if kickedNick == self.nick:
            time.sleep(10) #waits 10 seconds
            for channel in self.channel_list:
                connection.join(channel)

    def alt_on_quit(self, connection, event):
        """Log when users quit"""
        for channel in self.channels:
            if self.channels[channel].has_user(event.source.nick):
                self.log_message(channel, "info", "%s has quit" % (event.source))

    def on_join(self, connection, event):
        """Log channel joins"""
        self.log_message(event.target, "info", "%s joined the channel" % (event.source))
        if event.source.nick == self.nick:
            self.say(event.target, "Autobots, roll out!")

    def on_part(self, connection, event):
        """Log channel parts"""
        self.log_message(event.target, "info", "%s left the channel" % (event.source))

    def on_nick(self, connection, event):
        """Log nick changes"""
        oldNick = event.source.nick
        newNick = event.target
        for channel in self.channels:
            if self.channels[channel].has_user(newNick):
                self.log_message(channel, "info", "%s changed their nick to %s" % (event.source, newNick))

    def on_mode(self, connection, event):
        """Log mode changes"""
        mode = " ".join(event.arguments)
        self.log_message(event.target, "info", "mode changed to %s by %s" % (mode, event.source.nick))

    def on_topic(self, connection, event):
        """Log topic changes"""
        self.log_message(event.target, "info", 'topic changed to "%s" by %s' % (event.arguments[0], event.source.nick))

    #def on_action(self, connection, event):
    #    self.log_message(event.target, "action", event.source.nick + event.arguments[0])

    def on_pubmsg(self, connection, event):
        """Log public messages and respond to command requests"""
        channel = event.target
        nick = event.source.nick
        message = event.arguments[0]
        self.log_message(channel, nick, message)

        url_regex = re.compile(
            r'(?i)\b((?:https?://|[a-z0-9.\-]+[.][a-z]{2,4}/)'
            r'(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))'
            r'+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|'
            r'''[^\s`!()\[\]{};:'".,<>?«»“”‘’]))''', re.IGNORECASE)

        if url_regex.search(message):
            messageList = message.split(' ')
            for element in messageList:
                if url_regex.match(element):
                    title = url_announce.parse_url(element)
                    if title is not None:
                        self.say(channel, title)

        command_regex = re.compile(
            r'^(' + re.escape(self.nick) + '( |[:,] ?)'
            r'|' + re.escape(self.prefix) + ')'
            r'([^ ]*)( (.*))?$', re.IGNORECASE)

        if command_regex.match(message):
            command = command_regex.match(message).group(3)
            arguments = command_regex.match(message).group(5)
            if self.channels[channel].is_oper(nick):
                self.do_command(event, True, channel, command, arguments)
            else:
                self.do_command(event, False, channel, command, arguments)

    def on_privmsg(self, connection, event):
        """Log private messages and respond to command requests"""
        nick = event.source.nick
        message = event.arguments[0]
        self.log_message(nick, nick, message)
        command = message.partition(' ')[0]
        arguments = message.partition(' ')[2].strip(' ')
        if arguments == '':
            self.do_command(event, False, nick, command, None)
        else:
            self.do_command(event, False, nick, command, arguments)

    def do_command(self, event, isOper, source, command, arguments):
        """Commands the bot will respond to"""
        user = event.source.nick
        connection = self.connection
        message = event.arguments[0]
        if command == "hello":
            self.say(source, "hello " + user)
        elif command == "goodbye":
            self.say(source, "goodbye " + user)
        elif command == "ugm":
            self.say(source, "good (UGT) morning to all from " + user + "!")
        elif command == "ugn":
            self.say(source, "good (UGT) night to all from " + user + "!")
        elif command == "slap":
            if arguments is None or arguments.isspace():
                connection.action(source, "slaps " + user + " around a bit with a large trout")
            else:
                connection.action(source, "slaps " + arguments.strip(" ")  + " around a bit with a large trout")
        elif command == "rot13":
            if arguments is None:
                self.say(source, "I'm sorry, I need a message to cipher, try \"!rot13 message\"")
            else:
                self.say(source, codecs.encode(arguments, 'rot13'))
        elif command == "help":
            self.say(source, "Available commands: ![hello, goodbye, "
                                       "ugm, ugn, slap, rot13 <message>, "
                                       "disconnect, die, help]")
        elif command == "disconnect":
            if isOper:
                self.disconnect(msg="I'll be back!")
            else:
                self.say(source, "You don't have permission to do that")
        elif command == "die":
            if isOper:
                self.close_logs()
                self.die(msg="Bye, cruel world!")
            else:
                self.say(source, "You don't have permission to do that")
        else:
            connection.notice(user, "I'm sorry, " + user + ". I'm afraid I can't do that")

    def announce(self, connection, text):
        """Send notice to joined channels"""
        for channel in self.channel_list:
            connection.notice(channel, text)
            self.log_message(channel, "notice", connection.get_nickname() + ": " + text)

    def log_message(self, channel, nick, message):
        """Create IRC logs"""
        if channel not in self.logs:
            self.logs[channel] = LogFile.LogFile(datetime.datetime.utcnow().strftime(self.log_scheme).format(channel=channel))
        self.logs[channel].write("<{0}> {1}".format(nick, message))

    def refresh_logs(self):
        """Remove stale log files (15 min without writes)"""
        timestamp = int(time.time())
        for log in self.logs:
            if self.logs[log].is_stale(timestamp):
                self.logs[log].close()
                sys.stderr.write("closing " + log + "\n")

    def close_logs(self):
        """ Close all open log files"""
        for log in self.logs:
            self.logs[log].close()

class TCPinput(Thread):
    """Listen for data on a port and send it to Autobot.announce"""
    def __init__(self, connection, AutoBot, listenhost, listenport):
        Thread.__init__(self)
        self.setDaemon(1)
        self.AutoBot = AutoBot
        self.listenport = listenport
        self.connection = connection

        self.accept_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.accept_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.accept_socket.bind((listenhost, listenport))
        self.accept_socket.listen(10)

        self.accept_socket.setblocking(False)

        self.epoll = select.epoll()
        self.epoll.register(self.accept_socket.fileno(), select.EPOLLIN)

        self.stuff = {}

    def run(self):
        while True:
            for sfd, ev in self.epoll.poll():
                if sfd == self.accept_socket.fileno():
                    conn, addr = self.accept_socket.accept()
                    self.epoll.register(conn.fileno(), select.EPOLLIN)
                    self.stuff[conn.fileno()] = conn
                else:
                    conn = self.stuff[sfd]
                    buf = conn.recv(1024)
                    if not buf:
                        conn.close()
                        continue
                    self.AutoBot.announce(self.connection, buf.decode("utf-8", "replace").strip())

def main():
    config = configparser.ConfigParser()
    config.read("autobot.conf")
    network = config.get("irc", "network")
    port = int(config.get("irc", "port"))
    _ssl = config.getboolean("irc", "ssl")
    channels = [channel.strip() for channel in config.get("irc", "channels").split(",")]
    nick = config.get("irc", "nick")
    nickpass = config.get("irc", "nickpass")
    name = config.get("irc", "name")
    listenhost = config.get("tcp", "host")
    listenport = int(config.get("tcp", "port"))
    prefix = config.get("bot", "prefix")
    log_scheme = config.get("bot", "log_scheme")

    bot = AutoBot(nick, name, nickpass, prefix, log_scheme, channels, network, listenhost, listenport, port, _ssl)
    bot.start()

if __name__ == "__main__":
    main()
