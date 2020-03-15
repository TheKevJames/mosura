defmodule MosuraServer.EndpointTest do
  use ExUnit.Case, async: true
  use PlugTest

  @opts WebhookProcessor.Endpoint.init([])

  test "it is healthy" do
    conn = conn(:get, "/health")
    conn = WebhookProcessor.Endpoint.call(conn, @opts)

    assert conn.state == :sent
    assert conn.status == 200
    assert conn.resp_body == "ok"
  end
end
