# -*- coding: utf-8 -*-
#
# Copyright © 2012 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

from pulp.server import config as pulp_config
from pulp.server.dispatch import pickling
from pulp.server.dispatch.coordinator import Coordinator
from pulp.server.dispatch.scheduler import Scheduler, _run_via_coordinator
from pulp.server.dispatch.taskqueue import TaskQueue

# globals ----------------------------------------------------------------------

_COORDINATOR = None
_SCHEDULER = None
_TASK_QUEUE = None

# initialization ---------------------------------------------------------------

def _initialize_coordinator():
    global _COORDINATOR
    assert _COORDINATOR is None
    assert _TASK_QUEUE is not None
    task_wait_sleep_interval = 0.5
    _COORDINATOR = Coordinator(_TASK_QUEUE, task_wait_sleep_interval)


def _initialize_scheduler():
    global _SCHEDULER
    assert _SCHEDULER is None
    dispatch_interval = 30 # can make this configurable
    run_method = _run_via_coordinator
    _SCHEDULER = Scheduler(dispatch_interval, run_method)


def _initialize_task_queue():
    global _TASK_QUEUE
    assert _TASK_QUEUE is None
    concurrency_threshold = pulp_config.config.getint('tasking', 'concurrency_threshold')
    dispatch_interval = 0.5 # can make this configurable
    _TASK_QUEUE = TaskQueue(concurrency_threshold, dispatch_interval)


def initialize():
    # order sensitive
    pickling.initialize()
    _initialize_task_queue()
    _initialize_coordinator()
    _initialize_scheduler()

# factory functions ------------------------------------------------------------

def get_coordinator():
    assert _COORDINATOR is not None
    return _COORDINATOR


def get_scheduler():
    assert _SCHEDULER is not None
    return _SCHEDULER