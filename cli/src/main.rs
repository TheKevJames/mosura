extern crate clap;

mod settings;

use clap::{App, Arg, SubCommand};
use reqwest::blocking::Client;
use serde::Deserialize;
use settings::Settings;
use std::process::exit;

// TODO: share these definitions with apiserver
#[derive(Debug, Deserialize)]
struct Ticket {
    pub id: String,
    pub name: String,
}

#[derive(Debug, Deserialize)]
struct Tickets {
    pub items: Vec<String>,
}

fn main() {
    let matches = App::new("mosura")
        .version("0.1")
        .author("Kevin James <KevinJames@thekev.in>")
        .about("CLI interface for Mosura")
        .arg(
            Arg::with_name("v")
                .short("v")
                .multiple(true)
                .help("Sets the level of verbosity"),
        )
        .subcommand(
            SubCommand::with_name("ticket")
                .about("Commands for operating directly on tickets")
                .subcommand(
                    SubCommand::with_name("get")
                        .about("Gets a single ticket")
                        .arg(
                            Arg::with_name("ID")
                                .help("Sets the ID to lookup")
                                .required(true)
                                .index(1),
                        ),
                )
                .subcommand(SubCommand::with_name("list").about("Lists all available tickets")),
        )
        .get_matches();

    let settings = match Settings::new() {
        Ok(s) => s,
        Err(e) => {
            eprintln!("could not load settings: {:?}", e);
            exit(1);
        }
    };

    // TODO: set verbosity levels
    // match matches.occurrences_of("v") {
    //     0 => println!("No verbose info"),
    //     1 => println!("Some verbose info"),
    //     2 => println!("Tons of verbose info"),
    //     3 | _ => println!("Don't be crazy"),
    // }

    let client = Client::new();

    match matches.subcommand() {
        ("ticket", Some(m)) => match m.subcommand() {
            ("get", Some(x)) => {
                let id = x.value_of("ID").unwrap();
                let url = format!("{}/ticket/{}", settings.api, id);
                let request = client
                    .get(&url)
                    .header("User-Agent", "MosuraCLI")
                    .header("Authorization", format!("Bearer {}", &settings.token));
                match request.send() {
                    Ok(resp) => match resp.json() {
                        Ok(body) => {
                            let ticket: Ticket = body;
                            println!("{:?}", ticket);
                        }
                        Err(e) => eprintln!("error decoding response json: {:?}", e),
                    },
                    Err(e) => eprintln!("error making request: {:?}", e),
                }
            }
            ("list", Some(_)) => {
                let url = format!("{}/ticket", settings.api);
                let request = client
                    .get(&url)
                    .header("User-Agent", "MosuraCLI")
                    .header("Authorization", format!("Bearer {}", &settings.token));
                match request.send() {
                    Ok(resp) => match resp.json() {
                        Ok(body) => {
                            let tickets: Tickets = body;
                            println!("{:?}", tickets);
                        }
                        Err(e) => eprintln!("error decoding response json: {:?}", e),
                    },
                    Err(e) => eprintln!("error making request: {:?}", e),
                }
            }
            _ => {}
        },
        _ => {}
    }
}
