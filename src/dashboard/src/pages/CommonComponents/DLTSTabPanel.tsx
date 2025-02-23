import React from "react";
import Typography from '@material-ui/core/Typography';
import {Container, Grid, Paper, Toolbar} from "@material-ui/core";
import useCheckIsDesktop from "../../utlities/layoutUtlities";

interface TabPanelProps {
  children?: React.ReactNode;
  dir?: string;
  index: any;
  value: any;
  title?: any;
  className?: any;
}

export const DLTSTabPanel = (props: TabPanelProps) => {
  const { children, value, index, title, className, ...other } = props;
  return (
    <Container maxWidth={useCheckIsDesktop ? 'xl' : 'lg'}>
      <Typography
        component="div"
        role="tabpanel"
        hidden={value !== index}
        id={`full-width-tabpanel-${index}`}
        aria-labelledby={`full-width-tab-${index}`}
        {...other}
      >
        <Grid container alignItems={"center"}>
          <Grid item xs={12}>
            <Paper  style={{ marginTop: '10px', }}>
              <Toolbar>
                <Typography component="h2" variant="h6" className={className}>
                  {title}
                </Typography>
              </Toolbar>
              {children}
            </Paper>
          </Grid>
        </Grid>
      </Typography>

    </Container>
  )
}
