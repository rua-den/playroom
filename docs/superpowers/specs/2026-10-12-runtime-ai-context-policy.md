# Runtime AI và context — quality, economy, free

Ngày: 12/10/2026. Tài liệu này cụ thể hóa lựa chọn model mạnh khi có thể, vẫn chơi được bằng API miễn phí, và giữ dữ liệu độc lập với model. Đọc cùng [thiết kế chính](2026-10-12-personal-playroom-design.md); đây là contract để triển khai, không phải code đã chạy.

## 1. Ba vai trò, hai chế độ, một bộ dữ liệu

| Vai trò | Công việc | Quyền |
|---|---|---|
| Context director | Hiểu hành động và chọn/xếp hạng ký ức liên quan từ candidate pool | Trả ID và lý do ngắn; không sửa DB, không ghi đè canon |
| Narrator | Kể tiếp, diễn NPC, phản ứng và chuyển góc cảnh | Tạo candidate truyện; chưa trở thành lịch sử trước khi được chọn |
| Consolidator | Đề xuất sự kiện, trạng thái cảnh và tóm tắt từ lượt đã chốt | Chỉ tạo proposal có nguồn; không tự approve |

Các vai trò là operation trong một app, không phải ba agent tự trị hay một agent cho mỗi NPC. Có thể dùng cùng model/provider cho nhiều vai trò hoặc cấu hình riêng. Model viết code theo AGENTS là việc khác, không đi vào cấu hình AI của sản phẩm.

- `quality`: một context-director call, code validate/pack, rồi một narrator call. Nhắm tới hiểu diễn biến/hàm ý tốt hơn; chọn model bằng thử nghiệm.
- `economy`: bỏ context-director call, code chọn ký ức rồi gọi narrator một lần. Tóm tắt/trích xuất theo cảnh hoặc thao tác người chơi, không gọi thêm âm thầm mỗi lượt.
- Hai chế độ dùng cùng canon, scene, transcript, memory và checkpoint. Không có hai kho nhớ theo tier.
- Chế độ chất lượng và chính sách chi phí độc lập: quality có thể dùng model free nếu đủ capability/quota. Không coi model free mặc định là yếu hoặc model trả phí mặc định là kể hay.
- First-run dùng economy và `free_only` khi chưa có profile thanh toán được xác nhận. Người dùng có thể chọn quality khi đã cấu hình được context model, kể cả một API free phù hợp.

## 2. ModelProfile và chính sách chi phí

Mỗi profile có ID/version, provider protocol/endpoint, model ID, versioned secret reference, role capabilities, context window, max total output, token-count mode, reasoning/output accounting, supported reasoning parameters, credential tier, pricing source/timestamp và cap nếu dùng paid. Snapshot tham chiếu credential version đã xác minh, không tự lấy key/tier mới từ cùng một mutable name. Backend lưu secret riêng; API đọc chỉ trả masked status.

Ba role binding gồm `context_profile_id`, `narrator_profile_id`, `consolidation_profile_id`. Economy chỉ yêu cầu narrator. Profile thiếu structured output không được gắn cho director/consolidator; vẫn có thể dùng cho narrator văn bản và bộ nhớ thủ công.

- `free_only`: chỉ dùng provider/model/credential-tier được xác nhận phục vụ miễn phí; tắt paid tools/plugins và không có paid fallback. Model có free tier không đồng nghĩa một key thuộc paid project sẽ được miễn phí. Nếu billing eligibility/pricing chưa xác định, chặn call và yêu cầu xác nhận cấu hình thay vì hứa $0.
- `capped_paid`: chỉ bật sau khi người dùng chọn profile và xác nhận trần; preflight dựa trên input estimate và toàn bộ output allowance, bao gồm reasoning khi provider tính chung. Giá không xác định hoặc dự kiến vượt cap thì dừng trước dispatch.
- Cap của generation parent áp dụng tổng context + narration, không nhân cap theo số stage. Consolidation batch có tổng cap cho mọi chunk/combine job đã lập kế hoạch. Preflight tổng trước stage đầu; kiểm tra lại allowance còn lại trước mỗi stage; caps provider/key khi có được dùng thêm. Ước lượng/actual là hai giá trị riêng, không hứa một estimate là giới hạn billing cưỡng chế của provider.
- Provider-side usage/billing là nguồn chi phí thực. App hiển thị estimated/actual/unknown riêng; không suy ra chi phí bằng số chữ truyện hoặc trạng thái failed.
- Free hết quota/model unavailable: giữ draft và state, báo lựa chọn đợi hoặc chọn profile khác. Không tự đổi provider, paid model hoặc mode. Nếu không còn model khả dụng, xem/sửa/lưu/xuất vẫn hoạt động nhưng không sinh truyện mới.
- Model profile có cấu hình/giá/capability theo thời điểm; không hardcode availability hoặc quota trong logic app.

Candidate để thử, chưa phải lựa chọn đã nghiệm thu: `gpt-6.1-sol` cho quality director/consolidator; đối chiếu `gpt-6-astra` nếu cần; Gemini API free-tier hoặc một OpenRouter free variant cụ thể cho economy/quality tùy capability. Không dùng router chọn ngẫu nhiên model cho chiến dịch vì dễ đổi giọng không rõ nguyên nhân. Snapshot/model ID, tier và capability thực phải kiểm tra tại lúc cấu hình.

Nguồn hiện có: [OpenAI Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [Gemini quota](https://ai.google.dev/gemini-api/docs/rate-limits), [OpenRouter free variant](https://openrouter.ai/docs/guides/routing/model-variants/free). Các nguồn mô tả capability/giá, chưa chứng minh chất lượng roleplay tiếng Việt.

## 3. Candidate pool và SelectionPlan

Code lọc quyền, campaign, branch/checkpoint, revision và approval trước mọi tìm kiếm. Candidate pool chỉ gồm bản ghi effective đã duyệt. Ghim, canon bắt buộc, scene đã chốt và diễn biến chưa nén là mandatory và nằm ngoài việc director chọn bỏ.

Candidate pool mặc định tối đa 64 ký ức tùy chọn, ghép từ: nhân vật/focus scene, alias/keyword, lời hứa/việc chưa giải quyết, sự kiện cũ liên quan, và tóm tắt/chapter index. Ghi lý do và số lượng bị loại. Đây không phải khả năng tìm hiểu toàn bộ DB không giới hạn; fixture phải kiểm tra một lời hứa cũ không chỉ tồn tại ở 64 mục gần nhất.

`SelectionPlan` gồm checkpoint ID, action hash, ordered selected memory IDs (tối đa 20 tùy chọn), một lý do ngắn cho mỗi ID, relevant scene IDs và conflict flags. Director nhận dữ liệu nguồn, hành động, cảnh và ngữ cảnh gần đây trong budget riêng. Không yêu cầu lưu chain-of-thought; chỉ lưu lựa chọn/lý do có thể kiểm tra.

Code reject ID ngoài pool, record thuộc nhánh khác/pending, ID trùng, scene không tồn tại và payload sai schema. Đếm budget lần nữa sau selection, giữ mandatory, giảm optional nếu cần và ghi omission reason. Free-text “fact” do director tự tạo không được thêm vào prompt như sự thật hoặc ghi vào DB.

Quality không dùng director để duyệt canon. Tất cả dữ kiện được chốt vẫn cần quy tắc approval của app. Khi director fail/refuse/incomplete, dừng trước narrator; người dùng có thể chủ động thử economy trên cùng checkpoint với một request mới. Không fallback âm thầm.

Canon invariant (ví dụ hồ sơ chiều cao do người chơi chốt) khác dynamic state/sự kiện theo thời gian. Dynamic block ghi as-of cursor: một lời hứa/cảnh đã được cập nhật trong raw turn mới được chọn không bị bản memory cũ ghim đóng băng. Raw committed story là nguồn về diễn biến mới; proposal trích xuất vẫn chờ duyệt vì có thể diễn giải nguồn sai. Pin chỉ bảo đảm nhắc một record, không cho giá trị cũ thắng mọi sự kiện mới. Conflict với canon invariant cần cảnh báo/sửa, không coi một lời kể sai là retcon tự động.

`build_context_preview` ở Task 2 vẫn là phép dựng deterministic không gọi provider. Quality director chỉ chạy trong send job đã reserve, tạo final context run và snapshot mới trước narrator. “Xem context” thông thường không tiêu quota; context thực tế đã dùng ghi rõ director/model/selected IDs nếu có.

## 4. Request, attempt và reconnect

Một `GenerationJob` logic chứa request key, action, checkpoint, mode/policy/role-config hash và các `ProviderAttempt` stage `context` hoặc `narration`. Mỗi stage có key riêng, profile snapshot, payload hash, trạng thái queued/dispatched/completed/failed/interrupted, usage và offsets khi stream.

Reserve parent trong transaction trước bất kỳ provider call nào. Giữ guard của branch cho cả pipeline. Quality có đúng một context attempt và một narration attempt ở đường thành công; economy có đúng một narration attempt. Consolidation là job riêng do người chơi khởi động/duyệt kế hoạch. Tối đa hai attempt đang chạy toàn app; timeout mặc định 300 giây cho từng attempt.

Lost response/reconnect tra parent theo key và lấy stage hiện tại. Context attempt đã hoàn tất không chạy lại chỉ vì narrator stream bị ngắt. Server restart không replay một dispatched attempt còn mơ hồ; giữ kết quả đã lưu và đánh dấu interrupted, yêu cầu lựa chọn retry mới của người chơi. Không ghép output dở từ hai model thành một candidate hoàn chỉnh.

Structured result malformed, provider refusal, finish vì max tokens, timeout và quota exhaustion là trạng thái khác nhau. Normalize mã app: `SCHEMA_INVALID`, `MODEL_REFUSED`, `OUTPUT_TRUNCATED`, `PROVIDER_TIMEOUT`, `QUOTA_EXHAUSTED`, `MODEL_UNAVAILABLE`, `UNSUPPORTED_CAPABILITY`, `STATE_CONFLICT`; không công khai secret/raw provider stacktrace.

Đổi model/mode tăng `settings_revision`, không sửa `story_state_version`, checkpoint lịch sử hoặc memory. Preview cũ cần dựng lại nếu settings hash đổi; job đang chạy và candidate đã hoàn tất giữ profile snapshot đã dùng. Chỉ sửa dữ kiện truyện mới làm candidate stale theo story state.

UI báo cấu hình mới áp dụng cho request mới; job đang chạy giữ cost policy/model cũ và có nút cancel. Revoked/missing credential version gây failure, không lặng lẽ dùng key mới. Sau DB restore hoặc import một app export, job records chỉ để tra: không tự dispatch cả queued jobs cũ vì chúng có thể đã gọi provider sau thời điểm backup. Restore tạo execution epoch mới; chỉ thao tác mới của người chơi tạo attempt mới.

## 5. Budget và định dạng provider

Trần 12.000 input, 4.000 total output và 512 wrapper trong spec là điểm khởi đầu, không bảo đảm một chương dài sẽ vừa cho mọi model. Mỗi role có budget/cap riêng, bounded bởi capability model đã xác minh. Với API tính reasoning trong completion allowance, dự trữ toàn bộ allowance; visible narrative có thể ngắn hơn. Ghi usage thực, không công bố 4.000 token này là 4.000 token truyện nhìn thấy.

Narrator chỉ hoàn tất nếu adapter nhận terminal success và finish reason bình thường. Max-token/incomplete/refusal/stream lỗi giữ draft, không cho auto-commit; không tự trim paragraph/JSON cho trông hợp lệ. Đề xuất đổi output budget/độ dài cảnh phải hiện rõ và do người chơi chọn.

ProviderAdapter có `capabilities_for(profile)`, `generate_text(request)` và `generate_structured(request, schema)`, normalize outcome/usage/events. MVP có fake, một adapter text chat đã kiểm tra và một đường structured-capable đã chọn; không coi mọi endpoint “OpenAI-compatible” là cùng contract. Hỗ trợ free và quality ở cấp role/policy trước, không viết ba provider integration một lúc chỉ để tích tên.

Sau MVP phone trial, thêm adapter free thứ hai nếu phép thử cho thấy cần. Một provider có đủ tier/capability có thể phục vụ cả hai mode. JSON Schema chỉ kiểm định hình dạng; vẫn validate ID/nguồn và người chơi duyệt diễn giải. Nguồn: [OpenAI output token accounting](https://developers.openai.com/api/docs/guides/token-counting), [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output).

## 6. Điều kiện kiểm chứng

- Deterministic/fake: wrong-branch/pending/invented ID bị loại; mandatory không bị director bỏ; quality 2/economy 1 upstream attempt; quota fail không gọi paid fallback; đổi model giữ state; reconnect ở mỗi stage không nhân call; incomplete không auto-commit.
- Retrieval fixture: pool có lời hứa cũ và facts của cảnh đang diễn ra dù hành động chỉ dùng đại từ/ám chỉ; compare selected source IDs cho cả quality fake và economy.
- Model trial: dùng cùng checkpoint/action/style để so quality và economy, giữ narrator cố định khi so director để không nhầm tác dụng; sau đó so narrator free/paid riêng. Ghi quota/cost/latency và lỗi, không hứa tier nào luôn thắng.
- Capability thiếu/không có quota: test UI xem/sửa/export không phụ thuộc call model. Không thử API thật hoặc trả phí trong test tự động.
