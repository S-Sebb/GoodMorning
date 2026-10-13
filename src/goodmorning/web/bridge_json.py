"""Read bounded bridge JSON without retaining attachment bytes or private tool states."""
import json
import re

# Native tool states contain inputs, outputs and file content that the website
# never displays. Discard them before applying the visible response limit.
MESSAGE_PRIVATE_FIELDS = {b'state', b'providerState', b'providerResultState', b'metadata', b'snapshot'}
TOKENS = re.compile(rb'"|[{}\[\]:,]|[^"{}\[\]:,\s]+|\s+')


def read_json(response, limit=2_000_000, *, attachment_data=False, message_data=False):
    if not attachment_data and not message_data:
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ValueError('Upstream response exceeds limit')
        return json.loads(raw) if raw else {}
    # V2 prompt receipts and message pages echo files as {data: base64, ...}.
    # Keep the outer {data: object/array} envelope, but discard string-valued
    # data fields. This bridge never consumes file bytes from API responses.
    output = bytearray()
    in_string = skipping = escaped = False
    literal = bytearray()
    literal_size = 0
    last_key = None
    value_key = None
    discarding = False
    depth = 0
    scalar = False

    def append(value):
        output.extend(value)
        if len(output) > limit:
            raise ValueError('Upstream response exceeds limit')

    while chunk := response.read(65536):
        position = 0
        while position < len(chunk):
            if not in_string:
                for match in TOKENS.finditer(chunk, position):
                    token = match[0]
                    position = match.end()
                    if discarding and scalar and (token.isspace() or token in (b',', b'}', b']')):
                        discarding = scalar = False
                    if (not discarding and value_key in MESSAGE_PRIVATE_FIELDS and message_data
                            and not token.isspace()):
                        append(b'null')
                        discarding = True
                        scalar = token not in (b'"', b'{', b'[')
                    if token == b'"':
                        skipping = discarding or attachment_data and value_key == b'data'
                        if not discarding:
                            append(token)
                        in_string = True
                        escaped = False
                        literal.clear(); literal_size = 0
                        value_key = None
                        break
                    if discarding:
                        if token in (b'{', b'['):
                            depth += 1
                        elif token in (b'}', b']'):
                            depth -= 1
                            if depth == 0:
                                discarding = False
                        value_key = None
                        continue
                    append(token)
                    if token == b':':
                        value_key = last_key
                    elif not token.isspace():
                        value_key = last_key = None
                continue

            end = chunk.find(b'"', position)
            while end >= 0:
                start = end
                while start > position and chunk[start - 1] == 92:
                    start -= 1
                quote_escaped = bool((end - start) % 2) ^ (escaped if start == position else False)
                if not quote_escaped:
                    break
                end = chunk.find(b'"', end + 1)
            segment = chunk[position:end if end >= 0 else len(chunk)]
            if not skipping:
                append(segment)
                literal.extend(segment[:max(0, 40 - len(literal))])
                literal_size += len(segment)
            if end >= 0:
                if not discarding:
                    append(b'"')
                last_key = bytes(literal) if not skipping and literal_size <= 40 else None
                if discarding and depth == 0:
                    discarding = False
                in_string = False
                position = end + 1
            else:
                start = len(segment)
                while start > 0 and segment[start - 1] == 92:
                    start -= 1
                escaped = bool((len(segment) - start) % 2) ^ (escaped if start == 0 else False)
                break
    return json.loads(output) if output else {}
