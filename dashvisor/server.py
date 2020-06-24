from collections import OrderedDict

from supervisor import xmlrpc

try:
    import xmlrpc.client as xmlrpclib
except ImportError:
    import xmlrpclib
try:
    import http.client as httplib
except ImportError:
    import httplib
try:
    import urllib.parse as urlparse
except ImportError:
    import urlparse


class ExceptionHandler(object):
    def __init__(self, exc, defaults=None):
        self.exc = exc
        if defaults is None:
            defaults = False
        self.defaults = defaults

    def __call__(self, method):
        def wrap(self_, *args_, **kwargs_):
            try:
                return method(self_, *args_, **kwargs_)
            except self.exc:
                return self.defaults

        return wrap


class Server(object):
    def __init__(self, connection_string, id):
        self.name = urlparse.urlparse(connection_string).hostname
        self.connection = xmlrpclib.ServerProxy('http://127.0.0.1',
                               transport=xmlrpc.SupervisorTransport(
                                    None, None, serverurl=connection_string))
        self.status = OrderedDict()
        self.id = id

    @ExceptionHandler(httplib.CannotSendRequest)
    def refresh(self):
        self.status = OrderedDict(("%s:%s" % (i['group'], i['name']), i)
                                  for i in self.connection.supervisor.getAllProcessInfo())
        for key, program in self.status.items():
            program['id'] = key
            program['human_name'] = program['name']
            if program['name'] != program['group']:
                program['human_name'] = "%s:%s" % (program['group'], program['name'])

    @ExceptionHandler(httplib.CannotSendRequest)
    def stop(self, name):
        try:
            return self.connection.supervisor.stopProcess(name)
        except xmlrpclib.Fault as e:
            if e.faultString.startswith('NOT_RUNNING'):
                return False
            raise

    @ExceptionHandler(httplib.CannotSendRequest,
                      defaults={'content': '', 'size': 0, 'overflow': False})
    def tail(self, name, offset=-1, length=None):
        if length is None:
            length = 1024 * 5
        try:
            result = self.connection.supervisor.tailProcessLog(name, offset, length)
            return dict(zip(('content', 'size', 'overflow'), result))
        except xmlrpclib.Fault as e:
            raise

    @ExceptionHandler(httplib.CannotSendRequest)
    def start(self, name):
        try:
            return self.connection.supervisor.startProcess(name)
        except xmlrpclib.Fault as e:
            if e.faultString.startswith('ALREADY_STARTED'):
                return False
            raise

    @ExceptionHandler(httplib.CannotSendRequest)
    def supervisor_restart(self):
        """supervisor restart"""
        return self.connection.supervisor.restart()

    def supervisor_update(self, arg=''):
        supervisor = self.connection.supervisor
        try:
            result = supervisor.reloadConfig()
        except xmlrpclib.Fault as e:
            if e.faultCode == xmlrpc.Faults.SHUTDOWN_STATE:
                raise Exception('ERROR: already shutting down')
            else:
                raise

        added, changed, removed = result[0]
        valid_gnames = set(arg.split())

        # If all is specified treat it as if nothing was specified.
        if "all" in valid_gnames:
            valid_gnames = set()

        # If any gnames are specified we need to verify that they are
        # valid in order to print a useful error message.
        if valid_gnames:
            groups = set()
            for info in supervisor.getAllProcessInfo():
                groups.add(info['group'])
            # New gnames would not currently exist in this set so add those as well.
            groups.update(added)

            for gname in valid_gnames:
                if gname not in groups:
                    raise Exception('ERROR: no such group: %s' % gname)

        for gname in removed:
            if valid_gnames and gname not in valid_gnames:
                continue
            results = supervisor.stopProcessGroup(gname)
            # log(gname, "stopped")

            fails = [res for res in results if res['status'] == xmlrpc.Faults.FAILED]
            if fails:
                msg = "%s: %s" % (gname, "has problems; not removing")
                continue
            supervisor.removeProcessGroup(gname)
            # log(gname, "removed process group")

        for gname in changed:
            if valid_gnames and gname not in valid_gnames:
                continue
            supervisor.stopProcessGroup(gname)
            # log(gname, "stopped")

            supervisor.removeProcessGroup(gname)
            supervisor.addProcessGroup(gname)
            # log(gname, "updated process group")

        for gname in added:
            if valid_gnames and gname not in valid_gnames:
                continue
            supervisor.addProcessGroup(gname)
            # log(gname, "added process group")

        return {'added': added, 'changed': changed, 'removed': removed}

    def start_all(self):
        return self.connection.supervisor.startAllProcesses()

    def restart_all(self):
        self.stop_all()
        return self.start_all()

    def stop_all(self):
        return self.connection.supervisor.stopAllProcesses()

    def restart(self, name):
        self.stop(name)
        return self.start(name)
