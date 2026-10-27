# Playroom

App roleplay cá nhân bằng tiếng Việt, ưu tiên điện thoại và mở qua một link web riêng. Người chơi điều khiển nhân vật của mình; AI dẫn truyện và đóng vai các nhân vật còn lại.

Trọng tâm là quản lý context qua nhiều chương: lưu hồ sơ, cảnh, sự kiện, quan hệ, tóm tắt và transcript riêng; xem được AI đang dùng dữ kiện nào, sửa được khi nhớ sai, và giữ bộ nhớ đúng theo nhánh truyện.

## Trạng thái — 23/10/2026

**Mở bản test trên Windows:** Nhấp đúp **Start Playroom.cmd** để tạo tài khoản lần đầu và mở ứng dụng thật, hoặc **Try Playroom Demo.cmd** để thử giao diện bằng phản hồi mẫu. Xem [hướng dẫn bắt đầu](BAT-DAU.md).

**Chuyển giao hiện hành:** Đọc [nhánh truyện backend ngày 26/10](docs/handoff/2026-10-26-branch-fork.md), [sửa lỗi và UX sau audit ngày 23/10](docs/handoff/2026-10-23-audit-fixes.md), [rà từng màn UI/UX ngày 22/10](docs/handoff/2026-10-22-page-by-page-ux.md), [UI và tương tác ngày 22/10](docs/handoff/2026-10-22-interaction-polish.md), [hướng dẫn local](docs/handoff/2026-10-18-local-test-product.md) và [AGENTS.md](AGENTS.md) trước khi code; áp dụng chỉ dẫn routing mới nhất của owner trong chat. `main` của GitHub là source of truth. Bài viết/các SHAs bên dưới là bằng chứng tại từng mốc, không thay cho CI của commit tương lai.

**Sau audit 23/10:** Đã sửa liên kết key khi đổi custom endpoint sau lần lưu lỗi, chặn lưu cảnh khi chưa tải được dữ liệu, siết đúng chủ thể/cảm xúc người chơi, bổ sung chỉnh giọng/tính cách/kiến thức và style riêng, chọn người biết ký ức theo tên, nguồn tóm tắt theo lượt/đoạn trích, điều hướng Back/Forward và hạn trial theo giờ thiết bị. Có [backup/restore SQLite cục bộ](docs/backup-restore.md), không tự chạy lại job cũ hoặc khôi phục quyền trả phí. Regression 21 lượt dùng fake provider kiểm tra state/summary/cảnh/idempotency; chưa phải nghiệm thu chất lượng văn dài với AI thật.

- **Nhánh truyện (26/10)**: trong màn kể, mỗi lượt có **Tạo nhánh từ đây** và thanh **Nhánh truyện** để đọc lại nhánh khác. Nhánh kế thừa đúng transcript/hồ sơ/ký ức/cảnh tại checkpoint, giữ chuỗi duyệt import, nối tiếp số lượt và tách dữ liệu sau điểm fork. Reroll một lượt đã chốt hiện là hai bước (tạo nhánh rồi gửi lại); nhánh đang đọc chưa nằm trong URL. Xem [handoff](docs/handoff/2026-10-26-branch-fork.md).
- **B1–B3**: Send/reconnect, narrator JSON/cast/version và Chromium synthetic gameplay PASS ([PR #3](https://github.com/rua-den/playroom/pull/3), [#5](https://github.com/rua-den/playroom/pull/5), [#7](https://github.com/rua-den/playroom/pull/7), [#8](https://github.com/rua-den/playroom/pull/8)).
- **Ngân sách**: opt-in cumulative/per-send spending grants qua [PR #11](https://github.com/rua-den/playroom/pull/11), Free-first UI qua [PR #13](https://github.com/rua-den/playroom/pull/13), Gemma4 Cloud starter `gemma4:31b` qua [PR #16](https://github.com/rua-den/playroom/pull/16), cơ chế chặn rủi ro trừ credits mua thêm qua [PR #18](https://github.com/rua-den/playroom/pull/18). Giá/giới hạn nội bộ là dự toán, không phải bảo đảm hóa đơn provider.
- **Model thật đã gọi và PASS**: [Gemma4 synthetic 3-turn Action #38721810244](https://github.com/rua-den/playroom/actions/runs/38721810244), 3/3 lượt chuẩn JSON, Vy đúng ID/version; tổng **2.042 input + 513 output tokens**, chi phí tính toán **USD 0.00049108** (không phải hóa đơn). [CI tại cùng SHA #38721810166](https://github.com/rua-den/playroom/actions/runs/38721810166) PASS backend/frontend/Chromium. Thử nghiệm chỉ dùng Lan/Vy/Bình giả lập, **không** gửi BANGTAN/Henn riêng tư.
- **Import ChatGPT đã có ZIP/JSON + lịch sử dài/resume**: [PR #28](https://github.com/rua-den/playroom/pull/28) đặt nền import/review; các follow-up đã thêm ZIP, lịch sử dài và durable chunk/resume. Source gốc được giữ riêng, Send khóa tới khi owner duyệt checkpoint. [Issue #27](https://github.com/rua-den/playroom/issues/27) nay chỉ còn acceptance bằng **official ChatGPT export thật đã sanitize**; Legacy bundle không được dùng thay bằng chứng. [Issue #29](https://github.com/rua-den/playroom/issues/29) là đường riêng cho `playroom_legacy_story_bundle`, không bịa transcript còn thiếu.
- **Chỉ còn 2 external/manual gate mở**: [official ChatGPT export acceptance #27](https://github.com/rua-den/playroom/issues/27) và [điện thoại vật lý / VPS tùy chọn #9](https://github.com/rua-den/playroom/issues/9). [Narrator quality #61](https://github.com/rua-den/playroom/issues/61) đã đóng sau các guard production #77–#79 và [scorecard synthetic](docs/acceptance/2026-10-21-synthetic-story-quality-scorecard.md). [Reconnect #20](https://github.com/rua-den/playroom/issues/20) cũng đã đóng. App local hiện chơi được; chưa có production URL/physical-phone acceptance.
- **Phê duyệt chi phí:** Owner đã cho tối đa **USD 5** để kiểm chứng API với tình huống giả lập; đây là **trần rủi ro**, không phải mục tiêu tiêu hết hay cho phép gửi dữ liệu riêng, bỏ qua grant, hoặc tự đổi Caddy/VPS. Lần gọi thêm cần tuân thủ per-send/total grant và kiểm soát provider.

**Cập nhật review gate:** [PR #28](https://github.com/rua-den/playroom/pull/28) đã merge với bước duyệt checkpoint riêng, khóa Send bền trong SQLite và kiểm tra lại ngay trước provider dispatch, kể cả job cũ sau restart. Giao diện hiển thị hồ sơ/cảnh/ký ức, phạm vi biết và phần nguồn bị bỏ qua trước khi duyệt. Kiểm chứng độc lập local: **320 backend, 94 frontend PASS / 3 skipped, typecheck/build/Chromium PASS**. Flake reconnect lịch sử [#20](https://github.com/rua-den/playroom/issues/20) sau đó đã được chẩn đoán và đóng. [Handoff kiểm chứng](docs/handoff/2026-10-16-import-review-gate.md) giữ RED/GREEN và giới hạn lịch sử của slice JSON.

**Ưu tiên hiện tại:** không còn production-code blocker đã biết trong backlog mở. #27 chờ **official ChatGPT export thật đã sanitize** để acceptance; #9 chờ **physical phone** hoặc phê duyệt riêng nếu muốn deploy VPS/domain/Caddy. Legacy BANGTAN có thể import local ngay, nhưng owner vẫn phải tự duyệt canon và chủ động cho phép chia sẻ context trước Send. Về model kể chuyện, [scorecard 21/10](docs/acceptance/2026-10-21-synthetic-story-quality-scorecard.md) ưu tiên thử **Gemma4 31B** trước; player-agency, NPC knowledge và exact-time grounding đều được kiểm tra server-side bất kể model.

**Cập nhật reconnect:** [PR #31](https://github.com/rua-den/playroom/pull/31) đã merge tại `3e9d23a711b59f379e1728e94900175102a4dad2`: giữ bản nháp khi phản hồi commit/poll/recovery đến muộn và chặn cập nhật nhầm chiến dịch. Exact PR và merged-main CI đều xanh ngay attempt 1. Local: **320 backend, 102 frontend PASS / 3 skipped**, typecheck/build/Chromium PASS. #20 sau đó đã đóng completed ngày 19/10/2026; lịch sử timeout lost-POST vẫn được giữ làm bằng chứng regression.

**Runner local thật:** [PR #32](https://github.com/rua-den/playroom/pull/32) đã merge tại `4f22646c3ea2a9d2efa410921c0eedfb836fbcb7`, cung cấp `playroom-live-local` với SQLite/credentials bền và bind `127.0.0.1`. Exact PR và merged-main CI đều xanh attempt 1, backend Linux **334 PASS**, frontend **102 PASS / 3 skipped** và hai kịch bản Chromium PASS. [Handoff local live](docs/handoff/2026-10-16-owner-local-live.md) ghi CI và hướng dẫn tài khoản/khởi động. Authenticated real-app + provider + SQLite commit/reload đã PASS sau đó ở PR #42; #9 nay chỉ còn physical phone và VPS/domain tùy chọn.

**Legacy bundle #29 đã merge:** [PR #34](https://github.com/rua-den/playroom/pull/34) tại `2975dc1`, hỗ trợ nhập `playroom_legacy_story_bundle` vào chiến dịch cần duyệt, chuyển canon/sự kiện/quan hệ thành ký ức nguồn chờ duyệt, giữ riêng toàn bộ source và không tạo 156 lượt giả. Exact PR-head [CI #39051072648](https://github.com/rua-den/playroom/actions/runs/39051072648) và merged-main [CI #39051194140](https://github.com/rua-den/playroom/actions/runs/39051194140) đều PASS backend/frontend/Chromium synthetic. **File riêng đã qua nghiệm thu kỹ thuật import/review/reload trên ứng dụng loopback bằng DB tạm ngày 18/10; chưa duyệt checkpoint, chưa chia sẻ với model, chưa deploy**; xem [handoff 18/10](docs/handoff/2026-10-18-legacy-acceptance-followup.md).

**Follow-up import/review 18/10:** [PR #36](https://github.com/rua-den/playroom/pull/36) đã merge tại `1a726d0`, chặn kết quả bất đồng bộ của file cũ và reset xác nhận khi đổi snapshot, hiển thị hồ sơ/cảnh/phạm vi biết cùng metadata nguồn đầy đủ hơn. Exact PR-head [CI #39119446749](https://github.com/rua-den/playroom/actions/runs/39119446749) và merged-main [CI #39119578290](https://github.com/rua-den/playroom/actions/runs/39119578290) đều PASS attempt 1: **356 backend, 109 frontend / 3 skipped**, build/typecheck và hai kịch bản Chromium. Hai lỗi Chromium local lịch sử vẫn nằm trong handoff; #20 sau đó đã được chẩn đoán và đóng.

**ZIP/JSON cục bộ 18/10:** [PR #38](https://github.com/rua-den/playroom/pull/38) đã merge tại `fe8f888`. Final PR-head [CI #39141630371](https://github.com/rua-den/playroom/actions/runs/39141630371) và merged-main [CI #39141771466](https://github.com/rua-den/playroom/actions/runs/39141771466) đều PASS attempt 1: **357 backend, 136 frontend / 3 skipped**, build/typecheck/compile và hai kịch bản Chromium. Test ZIP giữ 125 lượt gốc, reload/duyệt, chặn request vượt budget trước provider, tự viết summary có nguồn rồi chủ động Gửi mới bằng fake provider. Các follow-up sau đó đã thêm durable chunk/resume cho lịch sử dài. [Handoff](docs/handoff/2026-10-18-chatgpt-zip.md) giữ bằng chứng lịch sử; #27 nay chỉ chờ official export thật, #20 đã đóng.

**Bản test Windows 19/10:** [PR #40](https://github.com/rua-den/playroom/pull/40) đã merge tại `e598e3f`; [PR CI #39189856947](https://github.com/rua-den/playroom/actions/runs/39189856947) và [main CI #39190075223](https://github.com/rua-den/playroom/actions/runs/39190075223) đều PASS attempt 1: **368 backend, 136 frontend / 3 skipped** và cả hai luồng Chromium. `Start Playroom.cmd` tạo tài khoản lần đầu qua mật khẩu ẩn và mở bản thật; `Try Playroom Demo.cmd` mở demo fake riêng. Cả hai tự build giao diện và mở trình duyệt khi server sẵn sàng. Xem [bắt đầu](BAT-DAU.md) và [bằng chứng/giới hạn thử AI thật](docs/handoff/2026-10-18-local-test-product.md).

**AI thật 19/10:** Lượt đầu dừng với `SCHEMA_INVALID`; sau sửa dữ liệu test, [lượt kiểm chứng riêng #39192040860](https://github.com/rua-den/playroom/actions/runs/39192040860) PASS: đăng nhập app, tạo và lưu một lượt truyện giả, tải lại vẫn còn. Tổng hai lượt gọi model, mỗi lượt đúng một request, không tự retry. Đây là kiểm tra luồng API bằng dữ liệu giả; key Actions không tự chuyển sang local. Dữ liệu truyện riêng vẫn chờ chủ sở hữu duyệt và quyết định cho phép gửi tới provider.

## Đọc theo thứ tự

1. [Thiết kế sản phẩm và context](docs/superpowers/specs/2026-10-12-personal-playroom-design.md).
2. [Runtime AI: quality, economy và free](docs/superpowers/specs/2026-10-12-runtime-ai-context-policy.md).
3. [Plan triển khai và các mốc nghiệm thu](docs/superpowers/plans/2026-10-12-personal-playroom-implementation-plan.md).
4. [Review plan và các vấn đề đã sửa](docs/superpowers/reviews/2026-10-12-personal-playroom-plan-review.md).
5. [Phân tích Whif APK](docs/references/whif-apk-analysis.md) và [mẫu kể chuyện playrooom](docs/references/playrooom-style-and-evaluation.md).

Agent đọc [AGENTS.md](AGENTS.md) trước khi thay đổi repo.

## Hướng kỹ thuật

- Giao diện: React + TypeScript + Vite, responsive ưu tiên điện thoại; PWA manifest để thêm vào màn hình chính trên trình duyệt hỗ trợ.
- Backend: Python + FastAPI + Uvicorn; bộ chọn context, phiên bản truyện và AI provider adapter tách riêng.
- Dữ liệu: SQLite trên thư mục lưu trữ bền, có nguồn dữ kiện và checkpoint của từng trạng thái.
- Deploy: VPS hiện có của người dùng, qua **Caddy đang hoạt động**; Playroom có service, thư mục, database và subdomain riêng.
- AI: OpenRouter và Ollama Cloud có luồng xác minh riêng; Custom / OpenAI-compatible cho phép nhập URL, model ID và key tùy chọn. Custom dùng giới hạn token mặc định, chi phí/quota do endpoint quản lý và giá được ghi nhận là chưa biết. Model/role được cấu hình riêng; API key nhập ở máy/server, không dùng session ChatGPT làm API access. Xem [hướng dẫn cấu hình](BAT-DAU.md).
- Domain dự kiến: https://play.nhkhuy.run.place; DNS/SSH/Caddy thực tế chưa được audit hay thay đổi.
- Quality có AI hỗ trợ chọn context; economy giảm số call. Cả hai giữ nguyên dữ liệu/style, có free-only policy và không tự chuyển paid khi hết quota.

## Các mốc

| Mốc | Kết quả cần có |
|---|---|
| Kiểm chứng context | Fixture 120 cặp lượt có summary coverage; chọn đúng nguồn, đúng nhánh và đúng budget |
| Bản chơi thử trên điện thoại | Đăng nhập, tạo/chơi chiến dịch, cấu hình AI/mode, sửa hồ sơ/bộ nhớ, khôi phục sau mất mạng; import lịch sử đầy đủ ở mốc sau |
| MVP chơi dài | Duyệt tóm tắt, tạo lại/rẽ nhánh, nhập phiên cũ, sao lưu/khôi phục và nghiệm thu model thật |

## Quyết định đã chốt

Canon do người chơi chốt không bị AI âm thầm ghi đè. Transcript gốc được giữ lại. Context theo budget thay vì gửi toàn bộ lịch sử. Fork dùng checkpoint gồm cả phiên bản hồ sơ/bộ nhớ; reconnect lấy request cũ thay vì tự gọi AI lại.

Caddy là thông tin mới nhất do người dùng xác nhận. Tài liệu Nginx/Certbot cũ của `wedding-online` chỉ dùng tham khảo lịch sử; không copy làm cấu hình Playroom.

Domain, model/API, tài nguyên và cấu hình VPS thực tế cần xác minh trước khi nối/deploy. Chất lượng kể chuyện và giữ mạch phải được kiểm chứng bằng phiên chơi thật, ngoài các test dữ liệu.

## Nhập ChatGPT ZIP/JSON (Issue #27)

Trong màn hình chiến dịch, chọn **Nhập ChatGPT**, rồi chọn ZIP hoặc các JSON conversation được đánh số. Tổng tệp đầu vào và riêng thread đã chọn tối đa **20 MiB**. ZIP được đọc trên thiết bị, có giới hạn **512 entry / 60 MiB giải nén**; chỉ một thread bạn chọn mới được gửi tới server Playroom đang mở để preview/import. Nội dung account và attachment không được nhập; bước này không gọi AI. Nếu ZIP của bản export dùng định dạng chưa hỗ trợ, giải nén bản export tin cậy trên thiết bị rồi chọn `conversations.json` hoặc các JSON đánh số.

Kiểm tra ID/thread, các lượt đầu/cuối, phần bị bỏ qua, persona và cast trước khi nhập; chiến dịch mới vẫn khóa Send đến khi duyệt checkpoint riêng. Lịch sử dài có thể vượt budget narrator: vào **Hồ sơ và ký ức → Ký ức → Tóm tắt**, chọn khoảng revision và tự viết/duyệt summary có nguồn trước khi chủ động Gửi lại. Transcript và source gốc vẫn được giữ nguyên; app không tự gọi AI để tóm tắt. Durable chunk/resume cho lịch sử dài đã có; phần chưa thể tuyên bố là tương thích mọi export ChatGPT cho tới khi một **official export thật đã sanitize** được chạy end-to-end. Xem [giới hạn và bằng chứng](docs/handoff/2026-10-18-chatgpt-zip.md).

## Nhập Legacy Story Bundle (Issue #29)

Nếu có tệp riêng `playroom_legacy_story_bundle` bản `1.0.0`, chạy **Playroom local thật** trước, rồi trong màn hình chiến dịch chọn **Nhập Legacy**. Chọn duy nhất file JSON (tối đa 20 MiB), xem preview đếm nhân vật/canon/sự kiện/trích đoạn và kiểm tra cảnh/chương hiện tại. App không gửi yêu cầu AI trong bước này; file được chuyển tới **server Playroom mà bạn đang mở** và lưu riêng trong SQLite. Không chọn server lạ nếu muốn giữ story chỉ trên máy cá nhân.

Nhấn **Tạo chiến dịch nháp để duyệt**: profile NPC, persona, cảnh và các ký ức canon/sự kiện/quan hệ được đưa vào trạng thái **chưa được xác nhận**, giữ nguyên nguồn đầy đủ trong bản lưu riêng, và **khóa Send** ở phía server. Timeline/chapter summaries **không phải** transcript; không tự tạo 156 lượt hay chương tiếp theo, không tự diễn vai người chơi. Rà soát đầy đủ ký ức nguồn đang chờ, phạm vi ai biết/cảnh có mặt và lịch sử thiếu; có thể từ chối hoặc sửa các phần không đúng. Duyệt checkpoint sẽ phê duyệt các đề xuất còn chờ theo đúng xác nhận người chơi.

Để mở khóa Send với Legacy, người chơi phải xác nhận riêng việc chia sẻ context riêng cho provider AI mà họ tự cấu hình **khi chủ động nhấn Send**; việc import hoặc duyệt không tạo model call. Nếu chưa muốn chia sẻ private story với cloud thì **không** đánh dấu ô này. Chế độ Local-only/không cấp quyền gửi là mặc định khóa. Repo GitHub, test fixture và CI chỉ có dữ liệu nhân tạo, không có file truyện riêng.

## Chạy demo cục bộ

Demo tổng hợp là chế độ opt-in riêng, chỉ bind loopback và không gọi model thật.

```powershell
rtk proxy uv sync --locked --extra test
rtk cmd /c "cd frontend && npm ci && npm run build"
rtk proxy uv run playroom-demo --data-dir .playroom-demo
```

Mở `http://127.0.0.1:8000`. Lần chạy đầu tạo owner password ngẫu nhiên an toàn và in password đúng một lần. Có thể tự đặt password tối thiểu 12 ký tự bằng `--password`; thư mục `.playroom-demo/` giữ SQLite và secrets để dữ liệu còn sau khi khởi động lại. Giao diện hiển thị nhãn synthetic/demo và narrative xác định để thử nhiều lượt.

Thêm `--email demo@example.test` nếu cần email khác. Không dùng thư mục demo hoặc `secure_cookies=False` cho production; production factory vẫn yêu cầu cấu hình provider/credential thật và cookie bảo mật.

## Chạy app thật trên máy cá nhân

`playroom-live-local` dùng runtime/provider thật và lưu SQLite cùng credentials trong `.playroom-live/`. Runner ép bind `127.0.0.1`; chỉ chế độ local HTTP này dùng cookie không có cờ Secure. Production vẫn giữ mặc định cookie bảo mật. Build frontend trước:

```powershell
rtk proxy uv sync --locked --extra test
rtk proxy npm --prefix frontend ci
rtk proxy npm --prefix frontend run build
```

Tạo tài khoản một lần bằng email muốn dùng; CLI hỏi mật khẩu qua input ẩn:

```powershell
rtk proxy uv run --locked playroom-owner create-owner --database-url .playroom-live/playroom.sqlite3 --email owner@example.test
```

Owner đầu tiên là admin và có thể quản lý tài khoản trong trang **Quản lý tài khoản**. Mật khẩu account mới phải dài ít nhất 12 ký tự; xóa account sẽ xóa truyện, dữ liệu và provider credentials của account đó.

Để thử riêng bằng dữ liệu test local, dùng một thư mục trống và cờ `--test-account`; cặp `admin` / `admin` chỉ được tạo nếu database chưa có owner. Runner chỉ bind loopback:

```powershell
rtk proxy uv run --locked playroom-live-local --data-dir .playroom-test --test-account
```

Mỗi lần chơi, chạy một lệnh và mở `http://127.0.0.1:8000`:

```powershell
rtk proxy uv run --locked playroom-live-local --data-dir .playroom-live
```

Đăng nhập, cấu hình/verify provider, chọn model và cấp grant nhỏ tường minh nếu cần; tạo chiến dịch giả lập hoặc import rồi duyệt checkpoint trước khi tự nhấn Gửi. Runner không tự tạo tài khoản, probe model hay gửi lượt mới khi khởi động. Job đã được bạn cho phép và còn queued có thể tiếp tục theo cơ chế recovery hiện có. Giữ kín thư mục dữ liệu và dùng lại nó khi khởi động sau. Thiếu frontend build hoặc chọn host khác sẽ báo lỗi.

[Hướng dẫn và bằng chứng local live](docs/handoff/2026-10-16-owner-local-live.md) phân biệt kiểm chứng Chromium dùng fake override với nghiệm thu Gemma4 thật còn ở #9. Dữ liệu BANGTAN/Henn riêng tư, điện thoại thật và VPS vẫn có ranh giới phê duyệt riêng.
