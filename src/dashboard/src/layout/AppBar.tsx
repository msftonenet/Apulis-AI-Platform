import React, { useCallback } from 'react';
import {
  AppBar,
  Box,
  Button,
  Grid,
  IconButton,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
  Slide,
  Toolbar,
  ListItem,
  List,
  Divider,
  ListItemText,
  Dialog,
  Modal,
  Snackbar,
  SnackbarContent,
  Hidden
} from '@material-ui/core';
import { createStyles, makeStyles, Theme } from '@material-ui/core/styles';
import {
  AccountBox,
  Check,
  ExitToApp,
  Group,
  HelpOutline,
  Info,
  MenuRounded,
  Dashboard,
} from '@material-ui/icons';
import CloseIcon from '@material-ui/icons/Close';
import { TransitionProps } from '@material-ui/core/transitions';
import DrawerContext from './Drawer/Context';
import UserContext from '../contexts/User';
import TeamContext from '../contexts/Teams';
import { Link, useHistory } from 'react-router-dom';
import _ from 'lodash';
import copy from 'clipboard-copy'
import { green, purple } from "@material-ui/core/colors";
import { SlideProps } from '@material-ui/core/Slide';
import AuthzHOC from '../components/AuthzHOC';
import axios from 'axios';


const useStyles = makeStyles((theme: Theme) =>
  createStyles({
    headerStyle: {
      backgroundColor: theme.palette.background.paper,
    },
    leftIcon: {
      marginRight: theme.spacing(1)
    },
    success: {
      backgroundColor: green[600],
    },
    title: {
      padding: theme.spacing(1)
    },
    titleLink: {
      textDecoration: 'none',
      color: purple[50]
    },
    appBar: {
      zIndex: theme.zIndex.drawer + 1
    },
    userLabel: {
      whiteSpace: 'nowrap',
      cursor: 'default'
    }
  })
);

const Transition = React.forwardRef<unknown, TransitionProps>(function Transition(props, ref) {
  return <Slide direction="up" ref={ref} {...props as SlideProps} />;
});

const OpenDrawerButton: React.FC = () => {
  const { setOpen, open } = React.useContext(DrawerContext);
  const onClick = React.useCallback(() => setOpen(!open), [setOpen, open]);
  return (
    <Tooltip title={open ? 'Hide' : 'Show'}>
      <IconButton edge="start" color="inherit" onClick={onClick}>
        <MenuRounded />
      </IconButton>
    </Tooltip>
  );
};

let TeamMenu: React.FC;
TeamMenu = () => {
  const { teams, saveSelectedTeam, selectedTeam } = React.useContext(
    TeamContext
  );

  const [open, setOpen] = React.useState(false);

  const button = React.useRef<any>(null);

  const onButtonClick = React.useCallback(() => setOpen(true), [setOpen]);
  const onMenuClose = React.useCallback(() => setOpen(false), [setOpen]);
  const onMenuItemClick = React.useCallback(
    team => () => {
      saveSelectedTeam(team);
      setOpen(false);
    },
    [saveSelectedTeam]
  );
  const styles = useStyles({});
  return (
    <>
      <Button
        ref={button}
        variant="outlined"
        color="inherit"
        onClick={onButtonClick}
        style={{ textTransform: 'none' }}
      >
        <Group className={styles.leftIcon} />
        {selectedTeam}
      </Button>
      <Menu
        anchorEl={button.current}
        open={open}
        onClose={onMenuClose}
        getContentAnchorEl={null}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
        transformOrigin={{ vertical: "top", horizontal: "center" }}>
        {_.map(teams, 'id').map((team: string) => (
          <MenuItem
            key={team}
            disabled={team === selectedTeam}
            onClick={onMenuItemClick(team)}
          >
            {team === selectedTeam ? (
              <Check className={styles.leftIcon} />
            ) : (
                <Group className={styles.leftIcon} />
              )}
            <Typography>{team}</Typography>
          </MenuItem>
        ))}
      </Menu>
    </>
  );
};

const UserButton: React.FC = () => {
  const { setOpen, open } = React.useContext(DrawerContext);
  const [viersonModalOpen,setVersionModalOpen] = React.useState(false);

  const [openUserProfile, setOpenUserProfile] = React.useState(false);
  const history = useHistory();
  const [openCopyWarn, setOpenCopyWarn] = React.useState(false);
  const [anchorEl, setAnchorEl] = React.useState<null | HTMLElement>(null);
  const { nickName, userName, permissionList, currentRole, userGroupPath } = React.useContext(UserContext);
  const styles = useStyles({});
  const handleClose = () => {
    setOpenUserProfile(false);
  };
  const handleCloseUserMenu = (event: React.MouseEvent<HTMLElement>) => {
    console.log(event.currentTarget)
    setAnchorEl(null);
  }

  const handleWarnClose = () => {
    setOpenCopyWarn(false);
  }
  const showUserProfile = () => {
    setAnchorEl(null)
  }
  const showVersion = () => {
    setOpen(false);
    setAnchorEl(null)
    history.push('/versionInfo');
  }
  const showHelp = () => {
    setOpen(false);
    setAnchorEl(null)
    history.push('/help');
  }
  
  const showUserMenu = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget);
  }
  const handleSignOut = () => {
    setAnchorEl(null);
    delete localStorage.token;
    clearAuthInfo(userGroupPath || '');
  }
  const handleCopy = useCallback((value) => {
    copy(value);
    setOpenCopyWarn(true)
  }, [])
  const classes = useStyles({})
  return (
    <main>
      <Button variant="outlined" color="inherit" style={{ marginRight: '10px' }} href={userGroupPath}>
        <Dashboard className={styles.leftIcon} />
        User Dashboard
      </Button>
      <Button variant="outlined" color="inherit" style={{ textTransform: 'none' }} onClick={showUserMenu} className={classes.userLabel} aria-controls="user-menu" aria-haspopup="true">
        <AccountBox className={styles.leftIcon} />
        {nickName || userName}
      </Button>
      <Menu
        id="user-menu"
        anchorEl={anchorEl}
        keepMounted
        getContentAnchorEl={null}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
        transformOrigin={{ vertical: "top", horizontal: "center" }}
        open={Boolean(anchorEl)}
        onClose={handleCloseUserMenu}
      >
        {/* <MenuItem onClick={showUserProfile}>Profile</MenuItem> */}
        <MenuItem onClick={showVersion}>
          <Info style={{ marginRight: 8 }} />
            Version
          </MenuItem>
        <MenuItem onClick={showHelp}>
          <HelpOutline style={{ marginRight: 8 }} />
            Help
          </MenuItem>
        <MenuItem onClick={handleSignOut} >
          <ExitToApp style={{ marginRight: 8 }} />
          Sign out
        </MenuItem>
      </Menu>
      <Dialog fullScreen open={openUserProfile} onClose={handleClose} TransitionComponent={Transition}>
        <AppBar>
          <Toolbar>
            <IconButton edge="start" color="inherit" onClick={handleClose} aria-label="close">
              <CloseIcon />
            </IconButton>
            <Typography variant="h6">
              {"Account Settings"}
            </Typography>
          </Toolbar>
        </AppBar>
        <Box m={10}>
          <List>
            <ListItem button>
              <ListItemText primary="NickName" secondary={nickName || '-'} onClick={() => handleCopy(nickName)} />
            </ListItem>
            <Divider />
            <ListItem button>
              <ListItemText primary="UserName" secondary={userName} onClick={() => handleCopy(userName)} />
            </ListItem>
            <Divider />
            <Divider />
            <ListItem button >
              <ListItemText primary="CurrentRole" secondary={currentRole?.join(', ')} />
            </ListItem>
            <Divider />
          </List>
        </Box>
        <Snackbar
          anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
          open={openCopyWarn}
          autoHideDuration={500}
          onClose={handleWarnClose}
          ContentProps={{
            'aria-describedby': 'message-id',
          }}
        >
          <SnackbarContent
            className={styles.success}
            aria-describedby="client-snackbar"
            message={<span id="message-id" >Copied Success</span>}
          />
        </Snackbar>
      </Dialog>
    </main>
  );
};
const clearAuthInfo = async (userGroupPath: string) => {
  delete localStorage.token
  await axios.get('/authenticate/logout');
  window.location.href = userGroupPath + '/user/login?' + encodeURIComponent(window.location.href);
}

const Title: React.FC = () => {
  const styles = useStyles({});
  return (
    <Box component="header" className={styles.title} display="flex">
      <Link to="/" className={styles.titleLink}>
        <Typography component="h1" variant="h6" align="left">
          Apulis
        </Typography>
      </Link>
    </Box>
  );
};

const DashboardAppBar: React.FC = () => {
  const styles = useStyles({});
  //const { open } = React.useContext(DrawerContext);
  return (
    <AppBar
      component="aside"
      position="fixed"
      className={styles.appBar}
    >
      <Toolbar>
        <Grid
          container
          wrap="nowrap"
          justify="flex-end"
          alignItems="center"
        >
          <Grid item>
            <OpenDrawerButton />
          </Grid>
          <Hidden xsDown>
            <Grid item xs>
              <Title />
            </Grid>
          </Hidden>
          <Grid item >
            <TeamMenu />
          </Grid>
          <Grid item style={{ marginLeft: '10px' }}>
            <UserButton />
          </Grid>
        </Grid>
      </Toolbar>
    </AppBar>
  );
};

export default DashboardAppBar;
