import argparse
import os


def main() -> None:
    parser = argparse.ArgumentParser(prog="local-ai")
    serve = parser.add_subparsers(dest="command", required=True).add_parser(
        "serve", help="run the local MLX OCR server"
    )
    serve.add_argument("--host", default=os.environ.get("OCR_HOST", "0.0.0.0"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("OCR_PORT", "8000")))
    serve.add_argument("--verbose", action="store_true", help="DEBUG console logging")
    args = parser.parse_args()

    from ocr_common import configure_logging

    configure_logging(verbose=args.verbose or os.environ.get("OCR_VERBOSE") == "1")
    import uvicorn

    uvicorn.run(
        "local_ai.app:app",
        host=args.host,
        port=args.port,
        workers=1,
        log_config=None,
    )


if __name__ == "__main__":
    main()
