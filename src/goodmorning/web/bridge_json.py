"""Read bounded bridge metadata without retaining native attachment base64 strings."""
import json


def read_json(response, limit=2_000_000, *, attachment_data=False):
    if not attachment_data:
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
    between = bytearray()
    last_data = False

    def append(value):
        output.extend(value)
        if len(output) > limit:
            raise ValueError('Upstream response exceeds limit')

    while chunk := response.read(65536):
        position = 0
        while position < len(chunk):
            if not in_string:
                end = chunk.find(b'"', position)
                if end < 0:
                    end = len(chunk)
                segment = chunk[position:end]
                append(segment)
                between.extend(segment)
                if end == len(chunk):
                    break
                skipping = last_data and between.strip() == b':'
                append(b'"')
                in_string = True
                escaped = False
                literal.clear(); literal_size = 0
                between.clear()
                position = end + 1
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
                literal.extend(segment[:max(0, 4 - len(literal))])
                literal_size += len(segment)
            if end >= 0:
                append(b'"')
                last_data = not skipping and literal_size == 4 and literal == b'data'
                in_string = False
                between.clear()
                position = end + 1
            else:
                start = len(segment)
                while start > 0 and segment[start - 1] == 92:
                    start -= 1
                escaped = bool((len(segment) - start) % 2) ^ (escaped if start == 0 else False)
                break
    return json.loads(output) if output else {}
