export function ApprovalPage() {
  return (
    <div className="approval-page">
      <h2>注册成功</h2>
      <p>您的注册申请已提交，请等待管理员审批。</p>
      <p className="approval-hint">
        审批通过后，您将收到短信/邮件通知，届时可获取 API Key 和嵌入代码。
      </p>
    </div>
  );
}
