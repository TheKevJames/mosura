defmodule MosuraServer.EndpointTest do
  use ExUnit.Case, async: true
  use Plug.Test

  @opts MosuraServer.Endpoint.init([])

  test "it is healthy" do
    conn = conn(:get, "/health")
    conn = MosuraServer.Endpoint.call(conn, @opts)

    assert conn.state == :sent
    assert conn.status == 200
    assert conn.resp_body == "ok"
  end
end
