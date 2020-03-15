defmodule MosuraServer.Endpoint do
  @moduledoc false

  require Logger
  use Plug.Router

  plug(Plug.Logger, log: :debug)
  plug(:match)
  plug(Plug.Parsers, parsers: [:json], json_decoder: Poison)
  plug(:dispatch)

  get("/health", do: send_resp(conn, 200, "ok"))

  # TODO: samples
  get "/test/1" do
    {status, body} =
      case Poison.encode(%{id: 1}) do
        {:ok, resp} -> {200, resp}
        {:error, err} -> {500, Poison.encode!(%{error: err})}
      end

    send_resp(conn, status, body)
  end

  post "/test" do
    {status, body} =
      case conn.body_params do
        %{"data" => data} -> {:ok, Poison.encode!(%{data: data})}
        _ -> {422, Poison.encode!(%{error: "missing data"})}
      end

    send_resp(conn, status, body)
  end

  # ENDTODO

  match(_, do: send_resp(conn, 404, "missing route"))
end
