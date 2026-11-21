import argparse
import os

from ocr_api.keygen import generate_key


def main() -> None:
    parser = argparse.ArgumentParser(prog="ocr-api")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("keygen", help="print a new API key")
    serve = commands.add_parser("serve", help="run the production API")
    serve.add_argument("--host", default=os.environ.get("OCR_HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("OCR_PORT", "8000")))
    serve.add_argument("--verbose", action="store_true", help="DEBUG console logging")
    args = parser.parse_args()

    if args.command == "keygen":
        print(generate_key())
        return

    from ocr_common import configure_logging

    configure_logging(verbose=args.verbose or os.environ.get("OCR_VERBOSE") == "1")
    import uvicorn

    uvicorn.run(
        "ocr_api.app:app",
        host=args.host,
        port=args.port,
        workers=1,
        log_config=None,
    )


if __name__ == "__main__":
    main()
