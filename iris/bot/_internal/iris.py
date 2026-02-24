from dataclasses import dataclass
import json # 추가됨 1
import requests
import typing as t
import base64
import os # 추가됨 2
from io import BufferedIOBase, BytesIO, BufferedReader
from PIL import Image
from urllib.parse import urlparse, unquote # 추가됨 3

@dataclass
class IrisRequest:
    msg: str
    room: str
    sender: str
    raw: dict
    
class IrisAPI:
    def __init__(self, iris_endpoint: str):
        self.iris_endpoint = iris_endpoint

    def __parse(self, res: requests.Response) -> dict:
        try:
            data: dict = res.json()
        except Exception:
            raise Exception(f"Iris 응답 JSON 파싱 오류: {res.text}")

        if not 200 <= res.status_code <= 299:
            print(f"Iris 오류: {res}")
            raise Exception(f"Iris 오류: {data.get('message', '알 수 없는 오류')}")

        return data
    
    # 추가됨 4
    def __ensure_list(self, files):
        if type(files) is not list:
            return [files]
        return files

    def __normalize_filename(
        self,
        filename: str | None,
        fallback: str,
        default_extension: str,
    ) -> str:
        candidate = os.path.basename(str(filename or "")).strip()
        if not candidate:
            candidate = fallback

        if "." not in candidate or candidate.endswith("."):
            candidate = f"{candidate.rstrip('.')}.{default_extension}"

        return candidate

    def __read_file_input(
        self,
        file: BufferedIOBase | bytes | str,
        idx: int,
        kind: str,
        default_extension: str,
    ) -> tuple[str, bytes] | None:
        fallback_name = f"{kind}_{idx}.{default_extension}"

        try:
            if isinstance(file, BufferedIOBase):
                name = getattr(file, "name", None)
                filename = self.__normalize_filename(
                    filename=str(name) if name else None,
                    fallback=fallback_name,
                    default_extension=default_extension,
                )
                return filename, file.read()

            if isinstance(file, bytes):
                return fallback_name, file

            if isinstance(file, str):
                if file.startswith("http"):
                    res = requests.get(file)
                    if res.status_code != 200:
                        print(f"{kind.capitalize()} download failed: {res.status_code}")
                        return None
                    content = res.content
                    parsed = urlparse(file)
                    filename = self.__normalize_filename(
                        filename=os.path.basename(unquote(parsed.path)),
                        fallback=fallback_name,
                        default_extension=default_extension,
                    )
                    return filename, content

                with open(file, "rb") as f:
                    content = f.read()
                filename = self.__normalize_filename(
                    filename=os.path.basename(file),
                    fallback=fallback_name,
                    default_extension=default_extension,
                )
                return filename, content

            print(f"Unsupported format: {type(file)}")
            return None
        except Exception as e:
            print(f"Error while processing {kind} input: {e}")
            return None

    def __build_multipart_files(
        self,
        files: t.List[BufferedIOBase | bytes | str],
        kind: str,
        default_extension: str,
    ) -> list[tuple[str, tuple[str, bytes, str]]]:
        multipart_files = []
        files = self.__ensure_list(files)

        for idx, file in enumerate(files):
            payload = self.__read_file_input(file, idx, kind, default_extension)
            if payload is None:
                continue
            filename, content = payload
            multipart_files.append(
                ("file", (filename, content, "application/octet-stream"))
            )

        return multipart_files

    def __reply_multipart(
        self,
        room_id: int,
        files: t.List[BufferedIOBase | bytes | str],
        single_type: str,
        multiple_type: str,
        kind: str,
        default_extension: str,
        list_as_multiple: bool = False,
        thread_id: int | None = None,
    ):
        is_list_input = type(files) is list
        multipart_files = self.__build_multipart_files(files, kind, default_extension)
        if len(multipart_files) == 0:
            print(f"No valid {kind} files to send.")
            return

        if list_as_multiple and is_list_input:
            payload_type = multiple_type
        else:
            payload_type = single_type if len(multipart_files) == 1 else multiple_type
        form_data = {"type": payload_type, "room": str(room_id)}
        if thread_id is not None:
            form_data["threadId"] = str(thread_id)

        res = requests.post(
            f"{self.iris_endpoint}/reply/multipart",
            data=form_data,
            files=multipart_files,
        )
        return self.__parse(res)
    # 추가끝 4

    def reply(self, room_id: int, msg: str, thread_id: int | None = None):
        json_data = {"type": "text", "room": str(room_id), "data": str(msg)}
        if thread_id is not None:
            json_data["threadId"] = str(thread_id)
        res = requests.post(
            f"{self.iris_endpoint}/reply",
            json=json_data,
        )
        return self.__parse(res)

    def reply_media(
        self,
        room_id: int,
        files: t.List[BufferedIOBase | bytes | Image.Image | str],
        thread_id: int | None = None,
    ):
        if type(files) is not list:
            files = [files]
        data = []
        for file in files:
            try:
                if isinstance(file, BufferedIOBase):
                    data.append(base64.b64encode(file.read()).decode())
                elif isinstance(file, bytes):
                    data.append(base64.b64encode(file).decode())
                elif isinstance(file, Image.Image):
                    image_bytes_io = BytesIO()
                    img = file.convert("RGBA")
                    img.save(image_bytes_io, format="PNG")
                    image_bytes_io.seek(0)
                    buffered_reader = BufferedReader(image_bytes_io)
                    data.append(base64.b64encode(buffered_reader.read()).decode())
                elif isinstance(file, str):
                    try:
                        if file.startswith("http"):
                            res = requests.get(file)
                            if res.status_code == 200:
                                file = res.content
                            else:
                                print(f"이미지 다운로드 실패: {res.status_code}")
                        else:
                            with open(file, "rb") as f:
                                file = f.read()
                        data.append(base64.b64encode(file).decode())
                    except Exception as e:
                        print(f"이미지 처리 중 오류 발생: {e}")
                else:
                    print(f"지원하지 않는 형식입니다: {type(file)}")
            except TypeError as e:
                print(f"이미지 처리 중 오류 발생: {e}")
                continue
        if len(data) > 0:
            json_data = {"type": "image_multiple", "room": str(room_id), "data": data}
            if thread_id is not None:
                json_data["threadId"] = str(thread_id)
            res = requests.post(
                f"{self.iris_endpoint}/reply",
                json=json_data,
            )
            return self.__parse(res)
        else:
            print("이미지 전송이 모두 실패하였습니다. 이미지 전송 요청 부분을 확인해주세요.")

    def decrypt(self, enc: int, b64_ciphertext: str, user_id: int) -> str | None:
        res = requests.post(
            f"{self.iris_endpoint}/decrypt",
            json={"enc": enc, "b64_ciphertext": b64_ciphertext, "user_id": user_id},
        )

        res = self.__parse(res)
        return res.get("plain_text")

    def query(self, query: str, bind: list[t.Any] | None = None) -> list[dict]:
        res = requests.post(
            f"{self.iris_endpoint}/query", json={"query": query, "bind": bind or []}
        )
        res = self.__parse(res)
        return res.get("data", [])

    def get_info(self):
        res = requests.get(f"{self.iris_endpoint}/config")
        return self.__parse(res)

    def get_aot(self):
        res = requests.get(f"{self.iris_endpoint}/aot")
        return self.__parse(res)

    # 추가됨 5
    def reply_audio(
        self,
        room_id: int,
        files: t.List[BufferedIOBase | bytes | str],
        thread_id: int | None = None,
    ):
        return self.__reply_multipart(
            room_id=room_id,
            files=files,
            single_type="audio",
            multiple_type="audio_multiple",
            kind="audio",
            default_extension="mp3",
            list_as_multiple=True,
            thread_id=thread_id,
        )

    def reply_video(
        self,
        room_id: int,
        files: t.List[BufferedIOBase | bytes | str],
        thread_id: int | None = None,
    ):
        return self.__reply_multipart(
            room_id=room_id,
            files=files,
            single_type="video",
            multiple_type="video_multiple",
            kind="video",
            default_extension="mp4",
            thread_id=thread_id,
        )

    def reply_file(
        self,
        room_id: int,
        files: t.List[BufferedIOBase | bytes | str],
        thread_id: int | None = None,
    ):
        return self.__reply_multipart(
            room_id=room_id,
            files=files,
            single_type="file",
            multiple_type="file_multiple",
            kind="file",
            default_extension="bin",
            thread_id=thread_id,
        )
    # 추가끝 5
