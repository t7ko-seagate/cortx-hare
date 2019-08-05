from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import json as j
from hax.types import Fid
from queue import Queue


class BaseMessage(object):
    pass


class Message(BaseMessage):
    def __init__(self, s):
        self.s = s


class EntrypointRequest(BaseMessage):
    def __init__(self,
                 reply_context=None,
                 req_id=None,
                 remote_rpc_endpoint=None,
                 process_fid=None,
                 git_rev=None,
                 pid=None,
                 is_first_request=None,
                 ha_link_instance=None):
        self.reply_context = reply_context
        self.req_id = req_id
        self.remote_rpc_endpoint = remote_rpc_endpoint
        self.process_fid = process_fid
        self.git_rev = git_rev
        self.pid = pid
        self.is_first_request = is_first_request
        self.ha_link_instance = ha_link_instance


class Die(BaseMessage):
    pass


class KVHandler(BaseHTTPRequestHandler):
    def __init__(self, req, client_addr, server):
        super().__init__(req, client_addr, server)
        self.server = server

    def _set_headers(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def do_GET(self):
        self._set_headers()
        s = j.dumps({'message': 'I am alive'})
        self.wfile.write(s.encode('utf-8'))

    def do_HEAD(self):
        self._set_headers()

    def do_POST(self):
        self._set_headers()
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        logging.debug('A new request has been received: {}'.format(post_data))

        struct = self.parse_req(post_data)
        struct = self.sanitize_service_info(struct)

        logging.info('Effective structure is as follows: {}'.format(struct))
        # TODO instead of this call something to m0d must be done
        self.server.halink.broadcast_service_states(struct)

    # Returns list of the following dicts:
    # {
    #   'fid' : <service fid>,
    #   'status': <either 'offline' or 'online'>
    #  }
    def sanitize_service_info(self, data):
        if not data:
            return []
        result = []
        for t in data:
            service = t.get('Service')
            checks = t.get('Checks')
            result.append({
                'fid': Fid.parse(service.get('ID')),
                'status': self.get_status(checks)
            })
        return result

    def get_status(self, checks):
        ok = all(map(lambda x: x.get('Status', None) == 'passing', checks))
        return 'online' if ok else 'offline'

    def parse_req(self, raw_data):
        try:
            struct = j.loads(raw_data.decode('utf-8'))
            return struct
        except j.JSONDecodeError:
            logging.warn('Not a valid JSON object received')
            return None


def run_server(queue,
               thread_to_wait=None,
               server_class=HTTPServer,
               port=8080,
               halink=None):
    port = 8080
    server_address = ('', port)
    httpd = server_class(server_address, KVHandler)
    httpd.reply_queue = queue
    httpd.halink = halink

    logging.info('Starting http server...')
    try:
        httpd.serve_forever()
    finally:
        queue.put(Die())
        if thread_to_wait is not None:
            thread_to_wait.join()
        logging.info('The http server has stopped')


def kv_publisher_thread(q: Queue):
    logging.info('Publisher thread has started')
    try:
        # client = consul.Consul()
        while True:
            logging.debug('Waiting')
            item = q.get()
            # import pudb; pudb.set_trace()
            logging.debug('Got something from the queue')
            if isinstance(item, Die):
                logging.debug('Got posioned pill, exiting')
                break
            elif isinstance(item, EntrypointRequest):
                item.ha_link_instance.send_entrypoint_request_reply(item)
                break
            else:
                logging.debug('Sending message to Consul: {}'.format(item.s))
            # TODO what and where do we actually need to persist to KV?
            # client.kv.put('bq', item)
    finally:
        logging.info('Publisher thread has exited')
