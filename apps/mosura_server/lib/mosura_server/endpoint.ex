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
      case MosuraServer.JiraProject.get(MosuraServer.JiraProject, id) do
        :error -> {404, Poison.encode!(%{error: "ticket #{id} not found"})}
        ticket -> {200, Poison.encode!(%{name: ticket.name})}
      end

    send_resp(conn, status, body)
  end

  get "/ticket" do
    {status, body} =
      case MosuraServer.JiraProject.list(MosuraServer.JiraProject) do
        :error -> {500, Poison.encode!(%{error: "tickets not found"})}
        tickets -> {200, Poison.encode!(%{tickets: tickets})}
      end

    send_resp(conn, status, body)
  end

  # post "/ticket" do
  #   {status, body} =
  #     case conn.body_params do
  #       %{"id" => id, "name" => name} ->
  #         ticket = %MosuraServer.Ticket{id: id, name: name}
  #         :ok = MosuraServer.Project.put(MosuraServer.Project, ticket)
  #         {200, ""}
  #
  #       _ ->
  #         {422, Poison.encode!(%{error: "bad payload"})}
  #     end
  #
  #   send_resp(conn, status, body)
  # end

  match(_, do: send_resp(conn, 404, "missing route"))
end
