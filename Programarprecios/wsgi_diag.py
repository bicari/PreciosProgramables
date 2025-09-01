def application(environ, start_response):
    import sys, platform
    out = []
    out.append(f"sys.version: {sys.version}")
    out.append(f"sys.executable: {sys.executable}")
    out.append(f"sys.prefix: {sys.prefix}")
    out.append(f"sys.base_prefix: {sys.base_prefix}")
    out.append(f"platform.architecture: {platform.architecture()}")
    try:
        import socket
        out.append(f"socket OK, module: {socket.__file__ if hasattr(socket,'__file__') else 'built-in'}")
    except Exception as e:
        out.append(f"socket ERROR: {e!r}")

    body = ("\n".join(out) + "\n").encode("utf-8")
    start_response("200 OK", [("Content-Type", "text/plain; charset=utf-8")])
    return [body]
