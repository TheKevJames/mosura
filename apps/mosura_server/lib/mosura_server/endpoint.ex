defmodule MosuraServer.Endpoint do
  @moduledoc false

  require Logger
  use Plug.Router

  plug(Plug.Logger, log: :debug)
  plug(:match)
  plug(Plug.Parsers, parsers: [:json], json_decoder: Poison)
  plug(:dispatch)

  get("/health", do: send_resp(conn, 200, "ok"))

  get "/ticket/:id" do
    {status, body} =
      case MosuraServer.Project.get(MosuraServer.Project, id) do
        {:ok, ticket} -> {200, Poison.encode!(%{name: ticket.name})}
        _ -> {404, Poison.encode!(%{error: "ticket #{id} not found"})}
      end

    send_resp(conn, status, body)
  end

  post "/ticket" do
    {status, body} =
      case conn.body_params do
        %{"id" => id, "name" => name} ->
          ticket = %MosuraServer.Ticket{id: id, name: name}
          :ok = MosuraServer.Project.put(MosuraServer.Project, ticket)
          {200, ""}

        _ ->
          {422, Poison.encode!(%{error: "bad payload"})}
      end

    send_resp(conn, status, body)
  end

  match(_, do: send_resp(conn, 404, "missing route"))
end
