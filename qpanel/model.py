# -*- coding: utf-8 -*-

#
# Class Qpanel for Asterisk
#
# Copyright (C) 2015-2017 Rodrigo Ramírez Norambuena <a@rodrigoramirez.com>
#

from __future__ import absolute_import
from __future__ import print_function
from sqlalchemy import Table, Column, Integer, Text, DateTime
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import exists
from .database import session_db, metadata, DeclarativeBase
from . import utils
from .config import QPanelConfig

cfg = QPanelConfig()
# Class queue_log Table
queue_log = Table(cfg.get('queue_log', 'queue_table'), metadata,
                  Column('time', DateTime, primary_key=True),
                  Column('callid', Text),
                  Column('queuename', Text),
                  Column('agent', Text),
                  Column('event', Text),
                  Column('data', Text),
                  Column('data1', Text),
                  Column('data2', Text),
                  Column('data3', Text),
                  Column('data4', Text),
                  Column('data5', Text))

cdr_log = Table(cfg.get('queue_log', 'table_cdr'), metadata,
                Column('cnum', Text),
                Column('calldate', DateTime, primary_key=True),
                Column('disposition', Text),
                Column('dcontext', Text))


class QueueLog(DeclarativeBase):
    __table__ = queue_log
    query = session_db.query_property()

    # relation definitions
    def as_dict(self):
        return {'time': self.time.split('.')[0],
                'callid': self.callid,
                'queuename': self.queuename,
                'agent': self.agent,
                'event': self.event,
                'data': self.data,
                'data1': self.data1,
                'data2': self.data2,
                'data3': self.data3,
                'data4': self.data4,
                'data5': self.data5}


class CDRLog(DeclarativeBase):
    __table__ = cdr_log
    query = session_db.query_property()

    def as_dict(self):
        return {
            'cnum': self.cnum,
            'time': self.calldate,
            'disposition': self.disposition,
            'dcontext': self.dcontext
        }


def queuelog_event_by_range_and_types(start_date, end_date, events=None,
                                      agent=None, queue=None, order=None, query=True):
    try:
        q = session_db.query(QueueLog)
        if start_date:
            q = q.filter(QueueLog.time >= start_date)
        if end_date:
            q = q.filter(QueueLog.time <= end_date)
        if events:
            q = q.filter(QueueLog.event.in_(events))
        if agent:
            q = q.filter(QueueLog.agent.in_(agent))
        if queue:
            q = q.filter(QueueLog.queuename == queue)

        if order is None:
            order = QueueLog.time.asc()

        q = q.order_by(order)

        if query:
            return q.all()

        return q

    except NoResultFound as e:
        print(e)
        return None


def queuelog_count_answered(start_date, end_date, agent=None, queue=None):
    events = ['CONNECTTT']
    data = queuelog_event_by_range_and_types(start_date, end_date, events,
                                             agent, queue)
    return len(data)


def queuelog_count_inbound(start_date, end_date, agent=None, queue=None):
    events = ['ENTERQUEUE']
    calls = []
    data = queuelog_event_by_range_and_types(start_date, end_date, events,
                                             agent, queue)

    for call in data:
        if call.callid not in calls:
            calls.append(call.callid)
    return len(calls)


def queuelog_count_abandon(start_date, end_date, agent=None, queue=None):
    events = ['ABANDON']
    data = queuelog_event_by_range_and_types(start_date, end_date, events,
                                             agent, queue)
    return len(data)


def queuelog_seconds_wait_abandon(start_date, end_date, agent=None,
                                  queue=None):
    events = ['ABANDON']
    seconds = 0
    data = queuelog_event_by_range_and_types(start_date, end_date, events,
                                             agent, queue)
    for call in data:
        seconds = seconds + int(call.data3)
    return seconds


def queuelog_seconds_wait(start_date, end_date, agent=None, queue=None):
    events = ['CONNECT']
    seconds = 0
    data = queuelog_event_by_range_and_types(start_date, end_date, events,
                                             agent, queue)
    for call in data:
        seconds = seconds + int(call.data1)
    return seconds


def queuelog_seconds_talking(start_date, end_date, agent=None, queue=None):
    events = ['COMPLETECALLER', 'COMPLETEAGENT']
    seconds = 0
    data = queuelog_event_by_range_and_types(start_date, end_date, events,
                                             agent, queue)
    for call in data:
        seconds = seconds + int(call.data2)
    return seconds


def parse_list_record(list):
    record = {}
    fields = ['callid', 'queuename', 'agent', 'event',
              'data1', 'data2', 'data3', 'data4', 'data5']

    # hardcore parse to date
    try:
        time = int(list[0])
        record['time'] = utils.dt(time)
    except:
        pass

    i = 1
    len_list = len(list)
    for f in fields:
        value = ''
        if i < len_list:
            value = list[i]
        record[f] = value
        i += 1
    return record


def queuelog_insert(log):
    if isinstance(log, list):
        log = parse_list_record(log)

    qlog = QueueLog()
    for val in log:
        if log[val] is not None:
            setattr(qlog, val, log[val])

    qlog.data = ''  # set backwards old compatibility

    try:
        session_db.add(qlog)
        session_db.commit()
        return True
    except Exception as e:
        print((str(e)))
        return False


def queuelog_exists_record(log):
    if isinstance(log, list):  # improveme later...sure
        log = parse_list_record(log)

    return session_db.query(
        exists().where(QueueLog.time == log['time']).
            where(QueueLog.event == log['event']).
            where(QueueLog.queuename == log['queuename']).
            where(QueueLog.callid == log['callid'])
    ).scalar()


def queuelog_data_queue(from_date, to_date, agent=None, queue=None):
    data = {}
    data['answered'] = queuelog_count_answered(from_date, to_date, agent,
                                               queue)
    data['inbound'] = queuelog_count_inbound(from_date, to_date, agent, queue)
    abandon = queuelog_count_abandon(from_date, to_date, agent, queue)

    # Some times the call only have ENTERQUEUE LOG. example
    '''
    SELECT id, time, callid, queuename as queue, event FROM queue_log
         WHERE callid = '1453142984.7';
    +-----+----------------------------+--------------+-------+------------+
    | id  | time                       | callid       | queue | event      |
    +-----+----------------------------+--------------+-------+------------+
    | 458 | 2016-01-18 15:49:45.464058 | 1453142984.7 | 5001  | DID        |
    | 459 | 2016-01-18 15:49:45.464635 | 1453142984.7 | 5001  | ENTERQUEUE |
    +-----+----------------------------+--------------+-------+------------+
    2 rows in set (0.00 sec)
    '''

    data['count_abandon'] = abandon + (data['inbound'] - data['answered']
                                       - abandon)
    data['seconds_wait'] = queuelog_seconds_wait(from_date, to_date,
                                                 agent, queue)
    data['seconds_talking'] = queuelog_seconds_talking(from_date, to_date,
                                                       agent, queue)
    data['seconds_wait_abandon'] = queuelog_seconds_wait_abandon(from_date,
                                                                 to_date,
                                                                 agent, queue)
    return data


def get_cdr(start=None, finish=None, members=None, dcontext=None):
    q = session_db.query(CDRLog)
    if start:
        q = q.filter(CDRLog.calldate >= start)

    if finish:
        q = q.filter(CDRLog.calldate <= finish)

    if members:
        q = q.filter(CDRLog.cnum.in_(members))

    if dcontext:
        q = q.filter(CDRLog.dcontext == dcontext)
    data = q.order_by(CDRLog.calldate.asc()).all()
    return data
